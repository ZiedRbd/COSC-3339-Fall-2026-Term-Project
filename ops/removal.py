"""
Removing things and bringing them back.

Nothing is erased. Removing a user, a team, a service, a building or a
ticket sets its flag and records who did it and when; restoring clears
all three. Only an administrator does either.

One rule covers the people who hold something the rest of the system
depends on: nobody is removed until someone else has taken it over. A
solver's upcoming shifts, a team's lead and a person named in an
escalation tier each have their own handover below, and remove_user
refuses until all three are done. A team hands its services to another
team in the same way before it can go.

Every function returns an Outcome: ok says whether it happened, and
messages holds the sentences saying what was done or why it was refused,
ready to show on a page. Each one checks everything first and only then
writes, so a refusal never leaves half a change behind.
"""
from collections import Counter

from django.db import transaction
from django.utils import timezone

from .access import is_admin
from .models import EscalationTier, Incident, Service, Shift, Team, TeamMember, User
from .notifications import notify
from .outcome import done, refused
from .scheduling import (_full_name, _window, assign_all_waiting, assign_waiting, release_to_queue, team_for,
                         validate_schedule)
from .timeline import MAX_REASON, clean_reason, log_event

UNFINISHED = ("open", "assigned", "in_progress")
HELD = ("assigned", "in_progress")
ADMIN_ONLY = "Only an administrator can do this"


def _count(number, word):
    """ "1 shift", "3 shifts". """
    return f"{number} {word}" if number == 1 else f"{number} {word}s"


def _it(number):
    """ "it" for one thing, "them" for several. """
    return "it" if number == 1 else "them"


def _lock(row):
    """
    Wait for anyone else who is changing this row right now, then read it
    again. Two people pressing the same button at the same moment are
    taken one after the other, and the second sees what the first did.
    """
    type(row).objects.select_for_update(no_key=True).filter(pk=row.pk).first()
    row.refresh_from_db()


def _mark_removed(row, by):
    """Who removed this row and when. The caller sets the flag and saves."""
    row.removed_by = by
    row.removed_at = timezone.now()


def _mark_restored(row):
    row.removed_by = None
    row.removed_at = None


# ── What a user holds ─────────────────────────────────────────────────


def holdings(user, team=None):
    """
    What other people depend on this user for, on one team or on every
    team: upcoming shifts as {team: how many}, the teams they lead, and
    the escalation tiers that name them. A removed team has no upcoming
    shifts and depends on nobody, so it does not count.
    """
    now = timezone.now()
    shifts = Shift.objects.filter(solver=user, ends_at__gt=now, team__is_active=True)
    led = Team.objects.filter(lead=user, is_active=True)
    tiers = EscalationTier.objects.filter(escalate_to="user", escalate_to_user=user, team__is_active=True)
    if team is not None:
        shifts, led, tiers = shifts.filter(team=team), led.filter(pk=team.pk), tiers.filter(team=team)
    by_team = Counter(shift.team for shift in shifts.select_related("team"))
    return {
        "shifts": dict(sorted(by_team.items(), key=lambda item: item[0].name)),
        "led": list(led.order_by("name")),
        "tiers": list(tiers.select_related("team").order_by("team__name", "tier_number")),
    }


def _what_is_held(user, held, lead=True):
    """One sentence for each thing that has to be handed over first."""
    name = _full_name(user)
    messages = [f"{name} holds {_count(count, 'upcoming shift')} on {team.name}. Transfer {_it(count)} first."
                for team, count in held["shifts"].items()]
    if lead:
        messages += [f"{name} is the lead of {team.name}. Appoint a new lead first." for team in held["led"]]
    messages += [f"Tier {tier.tier_number} of {tier.team.name} names {name}. Replace them in that tier first."
                 for tier in held["tiers"]]
    return messages


# ── The three handovers ───────────────────────────────────────────────


def _others_on(team, user):
    """The team's other active solvers, in name order."""
    return list(User.objects.filter(teammember__team=team, role="solver", is_active=True)
                .exclude(pk=user.pk).order_by("first_name", "last_name", "pk"))


def _busy_elsewhere(solver, team, starts_at, ends_at):
    """True when this solver is on call for another team, or secondary on this one, in these hours."""
    return (Shift.objects.filter(solver=solver, starts_at__lt=ends_at, ends_at__gt=starts_at, team__is_active=True)
            .exclude(team=team, on_call_role="primary").exists())


@transaction.atomic
def transfer_shifts(user, team, by, prefer=None):
    """
    The team's other solvers take over this user's upcoming primary
    shifts, so the team stays covered around the clock.

    Giving every shift to one person rarely works, because nobody may
    take two shifts in a row. So the shifts are walked in time order. A
    shift keeps its solver when it can. One that cannot, because it was
    this user's or because the handover just gave the shift before it to
    the same person, goes to `prefer` when they are free for it.
    Otherwise it goes to somebody who does not already have the shift
    right after it, and among those to whoever has been given the fewest
    so far. The result is checked with the same rules a lead's edit goes
    through. Nothing is saved if the handover would add a problem to the
    schedule; a problem that was already there is not this function's to
    judge.

    A shift this user is working right now is cut at this moment: they
    keep the part that is over and somebody else takes the rest. Their
    upcoming secondary shifts are dropped, since a secondary is optional.
    """
    if not is_admin(by):
        return refused(ADMIN_ONLY)
    _lock(user)
    now = timezone.now()
    name = _full_name(user)
    primaries = list(Shift.objects.select_for_update().filter(team=team, on_call_role="primary", ends_at__gt=now)
                     .order_by("starts_at", "pk"))
    secondaries = list(Shift.objects.select_for_update()
                       .filter(team=team, on_call_role="secondary", solver=user, ends_at__gt=now))
    mine = [shift for shift in primaries if shift.solver_id == user.pk]
    if not mine and not secondaries:
        return refused(f"{name} holds no upcoming shift on {team.name}")
    pool = _others_on(team, user)
    if prefer is not None and prefer not in pool:
        return refused(f"{_full_name(prefer)} is not an active solver on {team.name}")
    already_wrong = set(validate_schedule(team, primaries, now))

    cut = None              # this user's shift that is running now, which ends at this moment
    proposed = []           # the team's upcoming shifts as they will be
    changed = []            # the ones that get a new solver
    given = Counter()       # how many each solver has been handed
    before = None           # the shift before, as it will be
    before_changed = False
    for position, shift in enumerate(primaries):
        following = primaries[position + 1] if position + 1 < len(primaries) else None
        if shift.solver_id == user.pk and shift.starts_at < now:
            cut = shift
            shift = Shift(team=team, solver=user, on_call_role="primary", starts_at=now,
                          ends_at=shift.ends_at, created_by=by)
        # Two in a row only matters here when the handover caused it
        in_a_row = before.solver_id if before is not None and before.ends_at == shift.starts_at else None
        needs_someone = shift.solver_id == user.pk or (before_changed and shift.solver_id == in_a_row)
        if needs_someone:
            free = [solver for solver in pool if solver.pk != in_a_row
                    and not _busy_elsewhere(solver, team, shift.starts_at, shift.ends_at)]
            if not free:
                return refused(f"{team.name} cannot stay covered without {name}: nobody else can take the shift "
                               f"{_window(shift.starts_at, shift.ends_at)}. Add a solver to the team or change "
                               f"its schedule first.")
            # Whoever has the shift right after this one would end up with two in a row
            next_up = following.solver_id if following is not None and following.starts_at == shift.ends_at else None
            shift.solver = prefer if prefer in free else min(
                free, key=lambda solver: (solver.pk == next_up, given[solver], pool.index(solver)))
            given[shift.solver] += 1
            changed.append(shift)
        proposed.append(shift)
        before, before_changed = shift, needs_someone

    new_problems = [problem for problem in validate_schedule(team, proposed, now) if problem not in already_wrong]
    if new_problems:
        return refused(*new_problems)
    if cut is not None:
        cut.ends_at = now
        cut.save()
    for shift in changed:
        shift.save()
    for shift in secondaries:
        if shift.starts_at < now:
            shift.ends_at = now
            shift.save()
        else:
            shift.delete()

    for solver, count in given.items():
        notify(solver, None, "handover",
               f"You were given {_count(count, 'on-call shift')} on {team.name}. The schedule changed because "
               f"{name} no longer covers that team. Check the calendar for your hours.")
    messages = []
    if mine:
        takers = " and ".join(_full_name(solver) for solver in sorted(given, key=pool.index))
        messages.append(f"{name}'s {_count(len(mine), 'upcoming shift')} on {team.name} "
                        f"{'is' if len(mine) == 1 else 'are'} now covered by {takers}.")
    if secondaries:
        messages.append(f"{name}'s {_count(len(secondaries), 'secondary shift')} on {team.name} "
                        f"{'was' if len(secondaries) == 1 else 'were'} dropped. A secondary is optional.")
    return done(*messages)


@transaction.atomic
def appoint_lead(team, new_lead, by):
    """The team gets a new lead, who must be an active solver. Each team has exactly one."""
    if not is_admin(by):
        return refused(ADMIN_ONLY)
    _lock(team)
    if new_lead is None or new_lead.role != "solver" or not new_lead.is_active:
        return refused("The lead of a team has to be an active solver")
    if team.lead_id == new_lead.pk:
        return refused(f"{_full_name(new_lead)} already leads {team.name}")
    team.lead = new_lead
    team.save()
    notify(new_lead, None, "handover",
           f"You now lead {team.name}. You schedule its on-call shifts, set its escalation policy and can "
           f"reassign its tickets.")
    return done(f"{_full_name(new_lead)} now leads {team.name}.")


@transaction.atomic
def replace_in_tier(tier, new_person, by):
    """An escalation tier that names one person names another solver on the same team instead."""
    if not is_admin(by):
        return refused(ADMIN_ONLY)
    _lock(tier)
    team = tier.team
    if tier.escalate_to != "user":
        return refused(f"Tier {tier.tier_number} of {team.name} does not name a person")
    if (new_person is None or new_person.role != "solver" or not new_person.is_active
            or not TeamMember.objects.filter(user=new_person, team=team).exists()):
        return refused(f"A tier of {team.name} can only name an active solver on that team")
    if tier.escalate_to_user_id == new_person.pk:
        return refused(f"Tier {tier.tier_number} of {team.name} already names {_full_name(new_person)}")
    tier.escalate_to_user = new_person
    tier.save()
    told = f"Tier {tier.tier_number} of the escalation policy of {team.name} now names {_full_name(new_person)}."
    for person in {new_person, team.lead} - {None, by}:
        notify(person, None, "handover", told)
    return done(f"Tier {tier.tier_number} of {team.name} now names {_full_name(new_person)}.")


# ── Users ─────────────────────────────────────────────────────────────


@transaction.atomic
def remove_user(user, by):
    """
    The account can no longer log in, and its email stays taken. Refused
    while the user still holds a shift, leads a team or is named in a
    tier. The tickets they were working on go back to waiting.
    """
    if not is_admin(by):
        return refused(ADMIN_ONLY)
    if user.pk == by.pk:
        return refused("You cannot remove your own account")
    _lock(user)
    if not user.is_active:
        return refused(f"{_full_name(user)} is already removed")
    held = _what_is_held(user, holdings(user))
    if held:
        return refused(*held)
    name = _full_name(user)
    tickets = list(Incident.objects.select_for_update(of=("self",))
                   .filter(assigned_to=user, status__in=HELD, is_deleted=False))
    for ticket in tickets:
        release_to_queue(ticket)
        log_event(ticket, by, "removal", f"{name} was removed, so this ticket is waiting for a solver again.",
                  old_assignee=user)
    user.is_active = False
    _mark_removed(user, by)
    user.save()
    assign_all_waiting()
    messages = [f"{name} was removed and can no longer log in."]
    if tickets:
        messages.append(f"{_count(len(tickets), 'ticket')} went back to waiting for a solver.")
    return done(*messages)


@transaction.atomic
def restore_user(user, by):
    """The account can log in again. What it handed over stays with whoever took it."""
    if not is_admin(by):
        return refused(ADMIN_ONLY)
    _lock(user)
    if user.is_active:
        return refused(f"{_full_name(user)} is not removed")
    user.is_active = True
    _mark_restored(user)
    user.save()
    return done(f"{_full_name(user)} can log in again. Their shifts and roles stayed with whoever took them over.")


@transaction.atomic
def leave_team(user, team, by):
    """
    A solver comes off one team. The same rule as a removal, for that
    team only: their shifts and tiers there are handed over first. A lead
    may lead a team without being on it, so leading it does not hold them.
    """
    if not is_admin(by):
        return refused(ADMIN_ONLY)
    _lock(user)
    membership = TeamMember.objects.filter(user=user, team=team)
    if not membership.exists():
        return refused(f"{_full_name(user)} is not on {team.name}")
    held = _what_is_held(user, holdings(user, team), lead=False)
    if held:
        return refused(*held)
    name = _full_name(user)
    tickets = list(Incident.objects.select_for_update(of=("self",))
                   .filter(assigned_to=user, assigned_team=team, status__in=HELD, is_deleted=False))
    # The lead may hold a ticket of a team they are not on, so a lead who leaves keeps theirs
    if team.lead_id == user.pk:
        tickets = []
    for ticket in tickets:
        release_to_queue(ticket)
        log_event(ticket, by, "removal", f"{name} left {team.name}, so this ticket is waiting for a solver again.",
                  old_assignee=user)
    membership.delete()
    if team.is_active:
        assign_waiting(team)
    return done(f"{name} is no longer on {team.name}.")


# ── Services, buildings and teams ─────────────────────────────────────


@transaction.atomic
def remove_service(service, by):
    """No new ticket can be filed against it. The tickets it already has carry on."""
    if not is_admin(by):
        return refused(ADMIN_ONLY)
    _lock(service)
    if not service.is_active:
        return refused(f"{service.name} is already removed")
    service.is_active = False
    _mark_removed(service, by)
    service.save()
    tickets = list(Incident.objects.filter(service=service, status__in=UNFINISHED, is_deleted=False))
    for ticket in tickets:
        log_event(ticket, by, "removal", f"The service {service.name} was removed. This ticket carries on as normal.")
    messages = [f"{service.name} was removed. No new ticket can be filed against it."]
    if tickets:
        messages.append(f"Its {_count(len(tickets), 'open ticket')} "
                        f"{'carries' if len(tickets) == 1 else 'carry'} on as normal.")
    return done(*messages)


@transaction.atomic
def restore_service(service, by):
    """Tickets can be filed against it again, as long as the team that owns it is still there."""
    if not is_admin(by):
        return refused(ADMIN_ONLY)
    _lock(service)
    if service.is_active:
        return refused(f"{service.name} is not removed")
    team = service.owning_team
    if team is not None and not team.is_active:
        return refused(f"{service.name} belongs to {team.name}, which was removed. Restore that team first.")
    service.is_active = True
    _mark_restored(service)
    service.save()
    return done(f"{service.name} was restored.")


@transaction.atomic
def remove_building(building, by):
    """It leaves the ticket form. Tickets that point at it keep it."""
    if not is_admin(by):
        return refused(ADMIN_ONLY)
    _lock(building)
    if not building.is_active:
        return refused(f"{building.name} is already removed")
    building.is_active = False
    _mark_removed(building, by)
    building.save()
    return done(f"{building.name} was removed from the building list.")


@transaction.atomic
def restore_building(building, by):
    """It is offered on the ticket form again."""
    if not is_admin(by):
        return refused(ADMIN_ONLY)
    _lock(building)
    if building.is_active:
        return refused(f"{building.name} is not removed")
    building.is_active = True
    _mark_restored(building)
    building.save()
    return done(f"{building.name} was restored.")


@transaction.atomic
def move_services(team, to_team, by):
    """
    A team's handover: its services go to another team, the removed ones
    too, and its unfinished tickets follow them into that team's queue.
    """
    if not is_admin(by):
        return refused(ADMIN_ONLY)
    if to_team is None or not to_team.is_active or to_team.pk == team.pk:
        return refused("Choose another team that is still active to take the services")
    tickets = list(Incident.objects.select_for_update(of=("self",))
                   .filter(assigned_team=team, status__in=UNFINISHED, is_deleted=False))
    services = Service.objects.filter(owning_team=team).count()
    if not services and not tickets:
        return refused(f"{team.name} has no service or open ticket to move")
    Service.objects.filter(owning_team=team).update(owning_team=to_team)
    for ticket in tickets:
        holder = ticket.assigned_to
        ticket.assigned_team = to_team
        release_to_queue(ticket)
        log_event(ticket, by, "removal", f"This ticket moved from {team.name} to {to_team.name} with its service.",
                  old_assignee=holder)
    assign_waiting(to_team)
    return done(f"{_count(services, 'service')} and {_count(len(tickets), 'open ticket')} moved from "
                f"{team.name} to {to_team.name}.")


@transaction.atomic
def remove_team(team, by):
    """
    Refused while the team still owns a service or has an unfinished
    ticket. The team keeps its members, its policy and the shifts that
    were worked. Shifts that have not started are dropped and a shift
    running now ends at this moment, because a team that is gone covers
    nothing: its solvers are free for other teams, and may themselves be
    removed without anything to hand over.
    """
    if not is_admin(by):
        return refused(ADMIN_ONLY)
    _lock(team)
    if not team.is_active:
        return refused(f"{team.name} is already removed")
    services = Service.objects.filter(owning_team=team, is_active=True).count()
    tickets = Incident.objects.filter(assigned_team=team, status__in=UNFINISHED, is_deleted=False).count()
    messages = []
    if services:
        messages.append(f"{team.name} still owns {_count(services, 'service')}. "
                        f"Move {_it(services)} to another team first.")
    if tickets:
        messages.append(f"{team.name} still has {_count(tickets, 'open ticket')}. "
                        f"Move {_it(tickets)} to another team first.")
    if messages:
        return refused(*messages)
    now = timezone.now()
    upcoming = Shift.objects.filter(team=team, ends_at__gt=now)
    dropped = upcoming.filter(starts_at__gte=now).count()
    upcoming.filter(starts_at__gte=now).delete()
    upcoming.filter(starts_at__lt=now).update(ends_at=now)
    team.is_active = False
    _mark_removed(team, by)
    team.save()
    messages = [f"{team.name} was removed."]
    if dropped:
        messages.append(f"Its {_count(dropped, 'upcoming shift')} {'was' if dropped == 1 else 'were'} dropped.")
    return done(*messages)


@transaction.atomic
def restore_team(team, by):
    """
    The team is back with its members and its policy, and with no
    schedule: its lead has to lay one. Refused until the team has an
    active lead and every tier of its policy that names a person names
    one who is still an active solver on the team, so a restored team
    never depends on somebody who is gone.
    """
    if not is_admin(by):
        return refused(ADMIN_ONLY)
    _lock(team)
    if team.is_active:
        return refused(f"{team.name} is not removed")
    messages = []
    if team.lead is None or not team.lead.is_active or team.lead.role != "solver":
        messages.append(f"{team.name} has no active lead. Appoint one first.")
    for tier in team.escalation_tiers.filter(escalate_to="user").select_related("escalate_to_user"):
        person = tier.escalate_to_user
        if (person is None or not person.is_active or person.role != "solver"
                or not TeamMember.objects.filter(user=person, team=team).exists()):
            who = _full_name(person) if person is not None else "nobody"
            messages.append(f"Tier {tier.tier_number} of {team.name} names {who}, who cannot take a ticket for it. "
                            f"Replace them in that tier first.")
    if messages:
        return refused(*messages)
    team.is_active = True
    _mark_restored(team)
    team.save()
    return done(f"{team.name} was restored. Its services stayed with the team that took them.",
                f"It has no on-call schedule yet. {_full_name(team.lead)} has to add shifts before its tickets "
                f"can be assigned.")


# ── Tickets ───────────────────────────────────────────────────────────


@transaction.atomic
def remove_ticket(incident, by, reason):
    """An administrator deletes a ticket at any status. A reason is required and goes on the timeline."""
    if not is_admin(by):
        return refused(ADMIN_ONLY)
    reason = clean_reason(reason)
    if not reason:
        return refused("A reason is needed to remove a ticket")
    if len(reason) > MAX_REASON:
        return refused(f"The reason can be at most {MAX_REASON} characters")
    _lock(incident)
    if incident.is_deleted:
        return refused(f"Ticket #{incident.pk} is already removed")
    incident.is_deleted = True
    _mark_removed(incident, by)
    incident.save()
    log_event(incident, by, "removal", f"Ticket removed. Reason: {reason}")
    # A removed ticket's notifications leave the bell with it, so these two carry no ticket
    ticket = f"ticket #{incident.pk}, {incident.title},"
    if incident.reported_by_id != by.pk:
        notify(incident.reported_by, None, "override",
               f"Your {ticket} was removed by an administrator. Reason: {reason}")
    holder = incident.assigned_to
    if holder is not None and incident.status in HELD and holder.pk not in (by.pk, incident.reported_by_id):
        notify(holder, None, "override",
               f"The {ticket} which you held, was removed by an administrator. Reason: {reason}")
    # Its solver has room again for a ticket that was waiting
    assign_all_waiting()
    return done(f"Ticket #{incident.pk} was removed.")


@transaction.atomic
def restore_ticket(incident, by):
    """
    The ticket is back on every list. One that somebody was working on
    goes back to waiting, and the queue hands it out again, so nobody
    ends up holding more tickets than they may. An unfinished ticket
    goes to the team that handles its service today, which may not be
    the team it was with when it was removed.
    """
    if not is_admin(by):
        return refused(ADMIN_ONLY)
    _lock(incident)
    if not incident.is_deleted:
        return refused(f"Ticket #{incident.pk} is not removed")
    incident.is_deleted = False
    _mark_restored(incident)
    messages = [f"Ticket #{incident.pk} was restored."]
    if incident.status not in UNFINISHED:
        incident.save()
        log_event(incident, by, "restored", "Ticket restored.")
        return done(*messages)

    team = team_for(incident)
    incident.assigned_team = team
    if incident.status in HELD:
        holder = incident.assigned_to
        release_to_queue(incident)
        log_event(incident, by, "restored", "Ticket restored. It is waiting for a solver again.", old_assignee=holder)
    else:
        incident.save()
        log_event(incident, by, "restored", "Ticket restored.")
    if team is None:
        messages.append("No team handles its service now, so it will wait until one does.")
    else:
        assign_waiting(team)
    return done(*messages)
