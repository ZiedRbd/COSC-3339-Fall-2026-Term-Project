"""Who is on call, checking a schedule, and handing tickets to people."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import EscalationTier, Incident, Shift, Team, TeamMember, User
from .notifications import notify
from .timeline import log_event

# How many unfinished tickets one solver may hold at a time
MAX_ACTIVE_TICKETS = 3

# Every tier's wait is multiplied by this, so a critical ticket escalates
# twice as fast as a medium one and a low ticket half as fast
SEVERITY_FACTOR = {"critical": 0.5, "high": 0.75, "medium": 1, "low": 2}


def who_is_on_call(team, at=None, on_call_role="primary"):
    """
    The person on call for a team at a given moment, or None if nobody is.
    A shift runs from starts_at up to ends_at, and the ends_at moment
    itself already belongs to the next shift, so a ticket filed at
    exactly 16:00 goes to whoever starts at 16:00. Anyone who is
    deactivated, is not a solver, or is no longer on the team is skipped
    even if a shift names them. Primary by default; ask for the secondary
    with on_call_role="secondary".
    """
    if at is None:
        at = timezone.now()
    shift = (
        Shift.objects.filter(
            team=team,
            on_call_role=on_call_role,
            starts_at__lte=at,
            ends_at__gt=at,
            solver__is_active=True,
            solver__role="solver",
            solver__teammember__team=team,
        )
        .select_related("solver")
        .order_by("starts_at", "id")
        .first()
    )
    if shift is None:
        return None
    return shift.solver


def who_is_secondary_on_call(team, at=None):
    """The backup solver for a team at a given moment, or None."""
    return who_is_on_call(team, at, on_call_role="secondary")


def on_call_solvers(team, at=None):
    """Everyone on call right now, primary first, then secondary. Empty slots skipped."""
    return [s for s in (who_is_on_call(team, at), who_is_secondary_on_call(team, at)) if s is not None]


def active_ticket_count(solver):
    """How many unfinished tickets this solver holds. Resolved and Closed do not count."""
    return Incident.objects.filter(
        assigned_to=solver, status__in=("assigned", "in_progress"), is_deleted=False,
    ).count()


def pick_solver(team, at=None):
    """
    Who takes the next ticket: the primary while they hold fewer than
    MAX_ACTIVE_TICKETS, then the secondary while they do, otherwise None.
    """
    for solver in on_call_solvers(team, at):
        if active_ticket_count(solver) < MAX_ACTIVE_TICKETS:
            return solver
    return None


def on_call_roster(team, window_start, window_end, on_call_role="primary"):
    """
    All shifts for a team that fall inside a time window, for example one
    week of the calendar. A shift counts if any part of it is inside the
    window, so a shift that starts before the window but ends inside it
    is included. The list is sorted by start time, so the first item is
    the shift that starts soonest. Primary shifts by default; pass
    on_call_role=None for both roles.
    """
    shifts = Shift.objects.filter(team=team, starts_at__lt=window_end, ends_at__gt=window_start)
    if on_call_role:
        shifts = shifts.filter(on_call_role=on_call_role)
    return shifts.select_related("solver").order_by("starts_at", "id")


def assign_now(incident, by, at=None):
    """
    Hand an unassigned ticket to whoever is on call for the team that owns
    its service and still has room, and write what happened to the timeline
    either way. Used when a ticket is filed and when one is reopened. The
    ticket stays Open and unassigned when the service has no team, nobody is
    on call, or everyone on call already holds MAX_ACTIVE_TICKETS.
    Returns the solver it went to, or None.
    """
    team = incident.service.owning_team
    if team is None:
        log_event(incident, by, "assignment_failed",
                  f"Nobody is on call for {incident.service.name} right now, so this ticket is waiting to be assigned")
        return None
    incident.assigned_team = team
    # Anything already waiting is older and goes first, in case a slot
    # opened that nothing has handed out yet
    assign_waiting(team, skip=incident)
    solver = pick_solver(team, at)
    if solver is None:
        incident.save()
        if on_call_solvers(team, at):
            log_event(incident, by, "assignment_failed",
                      f"Everyone on call for {team.name} is full, so this ticket is waiting in the queue")
            _notify_about_queue(team, incident,
                                f"everyone on call for {team.name} holds {MAX_ACTIVE_TICKETS} tickets")
        else:
            log_event(incident, by, "assignment_failed",
                      f"Nobody is on call for {team.name} right now, so this ticket is waiting to be assigned")
        return None
    _hand_to(incident, solver, by, "assignment", f"Assigned to {_full_name(solver)}, on call for {team.name}",
             "assigned", "was assigned to you", at)
    return solver


def _start_clock(incident, at=None, level=0):
    """
    The ticket has a new owner: the escalation stopwatch starts from zero.
    A fresh assignment, a reassignment and a reopen start at tier 1,
    which is level 0; an escalation passes the level it moved to. Does
    not save.
    """
    incident.escalation_timer_started_at = at or timezone.now()
    incident.escalation_level = level
    incident.is_unassigned_after_escalation = False


def _ticket_label(incident):
    """How a notification names a ticket: its number, service and severity."""
    return f"Ticket #{incident.pk} ({incident.service.name}, {incident.priority})"


# What every assignment notification asks the solver to do
TAKE_IT = "Open it and move it to In Progress to take responsibility, or it escalates"


def _hand_to(incident, solver, by, update_type, body, event, happened, at=None, level=0):
    """
    The one place a ticket gets an owner. Sets the solver, starts the
    escalation clock, saves, writes the timeline entry and notifies the
    solver with the ticket number, service, severity and what to do next.
    """
    old = incident.assigned_to
    incident.assigned_to = solver
    if incident.status == "open":
        incident.status = "assigned"
    _start_clock(incident, at, level)
    incident.save()
    log_event(incident, by or solver, update_type, body, old_assignee=old, new_assignee=solver)
    action = TAKE_IT if incident.status == "assigned" else "It is already In Progress, so carry on with the work"
    notify(solver, incident, event, f"{_ticket_label(incident)} {happened}. {action}.")


def _waiting(team):
    """A team's Open tickets that nobody holds and that can be handed out, oldest first."""
    return Incident.objects.filter(
        assigned_team=team, status="open", assigned_to__isnull=True, is_deleted=False,
        is_unassigned_after_escalation=False,
    ).order_by("created_at", "id")


def _admins():
    return list(User.objects.filter(is_superuser=True, is_active=True))


def _lead_or_admins(team):
    """The team's lead, or the administrators when the team has no active lead."""
    if team.lead is not None and team.lead.is_active:
        return [team.lead]
    return _admins()


def _notify_about_queue(team, incident, why):
    """
    A ticket just started waiting. The lead hears about the first one
    waiting; the administrators hear about the second and each one after
    it. A team with no lead tells the administrators, and a site with no
    administrator tells the lead, so a waiting ticket is never silent.
    Tickets escalated to administration are not part of the queue.
    """
    waiting = _waiting(team).count()
    if waiting <= 1:
        people, count = _lead_or_admins(team), ""
    else:
        people, count = _admins() or _lead_or_admins(team), f" {waiting} tickets are waiting for {team.name}."
    for person in people:
        notify(person, incident, "queued",
               f"{_ticket_label(incident)} is waiting because {why}.{count} "
               f"It is assigned as soon as a solver on call has room.")


def assign_on_creation(incident):
    """A brand new ticket. The reporter filing it is recorded as the author."""
    return assign_now(incident, incident.reported_by, incident.created_at)


def assign_waiting(team, by=None, skip=None):
    """
    Every waiting ticket of this team gets another chance at the solvers
    on call right now. Runs every minute from the escalate command, and
    straight away whenever a slot may have opened: a ticket is resolved,
    closed, deleted or reassigned, a schedule changes, or a solver opens
    the list. Oldest ticket first, each one to whoever on call has room,
    stopping when nobody does. Quiet when it cannot assign: the ticket
    already says it is waiting. Pass the lead whose schedule change set
    this off as `by`; with nobody, the timeline says it was automatic.
    `skip` leaves one ticket out, for the caller that is assigning it
    itself. Returns how many tickets were assigned.
    """
    how = "Assigned" if by else "Assigned automatically"
    waiting = _waiting(team).exclude(pk=skip.pk) if skip is not None else _waiting(team)
    count = 0
    for incident in waiting:
        solver = pick_solver(team)
        if solver is None:
            break
        _hand_to(incident, solver, by, "assignment", f"{how} to {_full_name(solver)}, on call for {team.name}",
                 "assigned", "was assigned to you")
        count += 1
    return count


def assign_all_waiting():
    """Every team with a waiting ticket gets its queue handed out. Returns how many were assigned."""
    waiting_teams = Incident.objects.filter(
        status="open", assigned_to__isnull=True, is_deleted=False, is_unassigned_after_escalation=False,
        assigned_team__isnull=False,
    ).values("assigned_team_id")
    return sum(assign_waiting(team) for team in Team.objects.filter(id__in=waiting_teams))


def is_lead(user, team):
    """True when this user leads this team. One comparison, no query."""
    return team.lead_id == user.id


def _full_name(user):
    return f"{user.first_name} {user.last_name}".strip() or user.email


def _clock(t):
    t = timezone.localtime(t)
    return f"{t.hour}:{t.minute:02d}"


def _window(a, b):
    """A stretch of time in words, Chicago time: "Monday from 9:00 to 10:30"."""
    a_local, b_local = timezone.localtime(a), timezone.localtime(b)
    if a_local.date() == b_local.date():
        return f"{a_local:%A} from {_clock(a)} to {_clock(b)}"
    return f"{a_local:%A} {_clock(a)} to {b_local:%A} {_clock(b)}"


def _problem(what, a, b, from_now=False):
    """
    An error naming the day and the window, the way the spec asks:
    "Wednesday is missing coverage from 9:00 to 10:30", or across midnight
    "Missing coverage from Wednesday 22:00 to Thursday 6:00". A window that
    opens at this very moment says "from now (22:11)" so nobody thinks the
    check looked into the past.
    """
    a_local, b_local = timezone.localtime(a), timezone.localtime(b)
    if a_local.date() == b_local.date():
        opens = f"now ({_clock(a)})" if from_now else _clock(a)
        return f"{a_local:%A} is {what} from {opens} to {_clock(b)}"
    opens = f"now ({a_local:%A} {_clock(a)})" if from_now else f"{a_local:%A} {_clock(a)}"
    return f"{what.capitalize()} from {opens} to {b_local:%A} {_clock(b)}"


MAX_SHIFT = timedelta(hours=12)
MAX_SECONDARY_SHIFT = timedelta(hours=24)
SECONDARY_BREAK = timedelta(hours=24)


def _solver_problems(shift, team):
    """Why this person cannot take a shift on this team at all, as a list."""
    errors = []
    if shift.solver.role != "solver":
        errors.append(f"{_full_name(shift.solver)} is a reporter and cannot take a shift")
    if not TeamMember.objects.filter(user=shift.solver, team=team).exists():
        errors.append(f"{_full_name(shift.solver)} is not on {team.name}")
    return errors


def _already_on_call(clash):
    """The sentence for a person who is on call somewhere else in the same hours."""
    role = "secondary on call" if clash.on_call_role == "secondary" else "on call"
    return (f"{_full_name(clash.solver)} is already {role} for {clash.team.name} "
            f"{_window(clash.starts_at, clash.ends_at)}")


def validate_schedule(team, proposed, now=None):
    """
    Check a team's whole future primary schedule and return the list of
    problems, empty when it is fine. Shifts that already ended are
    ignored. Cover must run from now to the last shift with no gap and no
    overlap, one person may not be on call twice at once (another team,
    or secondary on this one), and only solvers who are on the team may
    take a shift. A shift is at most 12 hours and nobody takes two shifts
    in a row.
    """
    if now is None:
        now = timezone.now()
    errors = []
    for shift in proposed:
        if shift.ends_at <= shift.starts_at:
            errors.append(f"Shift on {timezone.localtime(shift.starts_at):%A} ends before it starts")
    # Inverted shifts are reported above and kept out of the other checks.
    # Shifts that already ended are history and kept out too.
    shifts = sorted([s for s in proposed if s.ends_at > s.starts_at and s.ends_at > now],
                    key=lambda s: s.starts_at)

    for shift in shifts:
        if shift.ends_at - shift.starts_at > MAX_SHIFT:
            errors.append(f"{_full_name(shift.solver)}'s shift on {timezone.localtime(shift.starts_at):%A} "
                          f"is longer than 12 hours")
        errors += _solver_problems(shift, team)
        # This team's other primary shifts are checked by the walk below
        clash = (
            Shift.objects.filter(solver=shift.solver, starts_at__lt=shift.ends_at, ends_at__gt=shift.starts_at)
            .exclude(team=team, on_call_role="primary")
            .exclude(id=shift.id)
            .select_related("team", "solver")
            .first()
        )
        if clash:
            errors.append(_already_on_call(clash))

    # Nobody works two shifts in a row: the person who just finished cannot
    # be the one who starts the next shift on the same team.
    for before, after in zip(shifts, shifts[1:]):
        if before.solver_id == after.solver_id and after.starts_at == before.ends_at:
            errors.append(f"{_full_name(after.solver)} cannot take two shifts in a row on {team.name} "
                          f"({_window(before.starts_at, after.ends_at)})")

    # Walk forward from now. Each shift should start exactly where the
    # cursor stands: later is a gap, earlier is a double booking. A shift
    # that is running right now started before now, which is fine.
    cursor = now
    for shift in shifts:
        start = max(shift.starts_at, now)
        if start > cursor:
            errors.append(_problem("missing coverage", cursor, start, from_now=cursor == now))
        elif start < cursor:
            errors.append(_problem("double booked", start, min(cursor, shift.ends_at)))
        cursor = max(cursor, shift.ends_at)
    return errors


def validate_secondary(team, proposed, now=None):
    """
    Check a team's future secondary shifts and return the list of
    problems, empty when it is fine. A secondary is optional, so hours
    with nobody are fine. A secondary shift is at most 24 hours, a team
    has one secondary at a time, nobody is on call twice at once in any
    role on any team, and a person rests 24 hours between their secondary
    shifts.
    """
    if now is None:
        now = timezone.now()
    errors = []
    shifts = sorted([s for s in proposed if s.ends_at > s.starts_at and s.ends_at > now],
                    key=lambda s: s.starts_at)
    saved_ids = [s.id for s in proposed if s.id]

    for shift in shifts:
        name = _full_name(shift.solver)
        if shift.ends_at - shift.starts_at > MAX_SECONDARY_SHIFT:
            errors.append(f"{name}'s secondary shift on {timezone.localtime(shift.starts_at):%A} "
                          f"is longer than 24 hours")
        errors += _solver_problems(shift, team)
        # Everything this person already has that is not one of the shifts being checked
        elsewhere = Shift.objects.filter(solver=shift.solver).exclude(id__in=saved_ids).select_related("team", "solver")
        clash = elsewhere.filter(starts_at__lt=shift.ends_at, ends_at__gt=shift.starts_at).first()
        if clash:
            errors.append(_already_on_call(clash))
        # 24 hours of rest between this person's secondary shifts, on any team
        others = [s for s in shifts if s is not shift and s.solver_id == shift.solver_id]
        others += list(elsewhere.filter(on_call_role="secondary"))
        for other in others:
            first, second = sorted((shift, other), key=lambda s: s.starts_at)
            rest = second.starts_at - first.ends_at
            if timedelta(0) <= rest < SECONDARY_BREAK:
                errors.append(f"{name} needs a 24 hour break between secondary shifts: one ends "
                              f"{timezone.localtime(first.ends_at):%A %H:%M} and the next starts "
                              f"{timezone.localtime(second.starts_at):%A %H:%M}")

    # One secondary at a time on a team
    for before, after in zip(shifts, shifts[1:]):
        if after.starts_at < before.ends_at:
            errors.append(_problem("double booked for the secondary", after.starts_at,
                                   min(before.ends_at, after.ends_at)))
    # A pair of shifts is seen from both sides, so say each thing once
    return list(dict.fromkeys(errors))


def reassign(incident, new_solver, by):
    """
    A team lead hands an active ticket to the primary or secondary solver
    on call for its team right now, and to nobody else, and only while
    that solver holds fewer than MAX_ACTIVE_TICKETS. Returns the reason it
    was refused, or None when it worked. Writes a reassignment entry
    naming the old and the new solver.
    """
    team = incident.assigned_team
    if team is None:
        return "No team handles this ticket's service, so nobody can be assigned"
    if not is_lead(by, team):
        return f"Only the lead of {team.name} can reassign its tickets"
    if incident.status in ("resolved", "closed"):
        return "Only active tickets can be reassigned"
    if new_solver is None:
        return f"Nobody is on call for {team.name} right now"
    if new_solver not in on_call_solvers(team):
        return f"{_full_name(new_solver)} is not on call for {team.name} right now"
    old = incident.assigned_to
    if old == new_solver:
        return f"{_full_name(new_solver)} already has this ticket"
    if active_ticket_count(new_solver) >= MAX_ACTIVE_TICKETS:
        return f"{_full_name(new_solver)} already holds {MAX_ACTIVE_TICKETS} tickets"
    _hand_to(incident, new_solver, by, "reassignment",
             f"Reassigned from {_full_name(old) if old else 'nobody'} to {_full_name(new_solver)}",
             "assigned", "was reassigned to you")
    # The solver who let go may now have room for a ticket that was waiting, on any team they cover
    assign_all_waiting()
    return None


def ensure_policy(team):
    """
    Every team has a policy. A team that has none gets the default one:
    the on-call solver has 5 minutes, then the lead has 10. An
    Administration row on its own is not a policy, since nobody waits at
    it: it is moved after the two default tiers.
    """
    if not team.escalation_tiers.exclude(escalate_to="administration").exists():
        team.escalation_tiers.filter(escalate_to="administration").update(tier_number=3)
        EscalationTier.objects.bulk_create([
            EscalationTier(team=team, tier_number=1, escalate_to="on_call", wait_minutes=5),
            EscalationTier(team=team, tier_number=2, escalate_to="lead", wait_minutes=10),
        ])


def escalate_due(now=None):
    """
    Runs once a minute. Looks at every Assigned ticket, works out how long
    it may wait at its current tier, and moves the ones that waited too
    long. Each ticket is read again and locked just before it is judged,
    so a solver who starts work while the job runs keeps the ticket.
    Returns how many moved.
    """
    now = now or timezone.now()
    moved = 0
    due = Incident.objects.filter(status="assigned", is_deleted=False, assigned_team__isnull=False)
    for pk in list(due.values_list("pk", flat=True)):
        with transaction.atomic():
            incident = (
                Incident.objects.select_for_update(of=("self",))
                .select_related("assigned_team", "assigned_to", "service")
                .filter(pk=pk, status="assigned", is_deleted=False, assigned_team__isnull=False)
                .first()
            )
            if incident is not None and _escalate_if_overdue(incident, now):
                moved += 1
    return moved


def _minutes(amount):
    """A wait in words: 7.5 is "7.5 minutes", 5.0 is "5 minutes", 1 is "1 minute"."""
    return f"{amount:g} minute{'' if amount == 1 else 's'}"


def _escalate_if_overdue(incident, now):
    """Move one Assigned ticket up if it has waited out its tier. True when it moved."""
    if incident.escalation_timer_started_at is None:
        # Assigned before the clock existed, so its wait starts now
        incident.escalation_timer_started_at = now
        incident.save(update_fields=["escalation_timer_started_at"])
        return False
    ensure_policy(incident.assigned_team)
    rows = list(incident.assigned_team.escalation_tiers.select_related("escalate_to_user").order_by("tier_number"))
    # Administration is not a tier anyone waits at. It only says how the policy ends.
    tiers = [tier for tier in rows if tier.escalate_to != "administration"]
    to_administration = len(tiers) < len(rows)
    # escalation_level counts the tiers the ticket has left behind, so it is
    # the position of the tier it sits at. If the lead has shortened the
    # policy since, a ticket that was further along sits at the last tier.
    position = min(incident.escalation_level, len(tiers) - 1)
    minutes = tiers[position].wait_minutes * SEVERITY_FACTOR.get(incident.priority, 1)
    if now - incident.escalation_timer_started_at < timedelta(minutes=minutes):
        return False
    _move_up(incident, tiers, position, minutes, now, to_administration)
    return True


def _person_at(tier, team, holder):
    """
    Who a tier can give the ticket to right now, or None. Never the person
    who already holds it, never anyone deactivated or already holding
    MAX_ACTIVE_TICKETS, and a named person only while they are still a
    solver on the team.
    """
    if tier.escalate_to == "on_call":
        candidates = on_call_solvers(team)
    elif tier.escalate_to == "lead":
        candidates = [team.lead]
    else:
        person = tier.escalate_to_user
        on_team = (person is not None and person.role == "solver"
                   and TeamMember.objects.filter(user=person, team=team).exists())
        candidates = [person] if on_team else []
    for person in candidates:
        if (person is not None and person.is_active and person != holder
                and active_ticket_count(person) < MAX_ACTIVE_TICKETS):
            return person
    return None


def _move_up(incident, tiers, position, minutes, now, to_administration=False):
    """
    An overdue ticket leaves its tier for the first later tier that has
    somebody to take it. A tier with nobody available is passed over and
    named on the timeline. When no later tier has anyone, the ticket goes
    back to Open and is flagged as unassigned, and only the lead can hand
    it out again. A team whose lead ticked Administration on the policy
    page has it as the last tier: the timeline says the ticket was
    escalated to administration and the administrators are told with the
    lead. Without the tick the policy just runs out and the lead is told.
    """
    team = incident.assigned_team
    holder = incident.assigned_to
    author = holder or incident.reported_by
    severity = "" if SEVERITY_FACTOR.get(incident.priority, 1) == 1 else f" for a {incident.priority} ticket"
    reason = f"{_full_name(holder) if holder else 'Nobody'} did not start work within {_minutes(minutes)}{severity}"
    incident.escalated_at = now

    passed = []

    def skipped():
        if not passed:
            return ""
        return f" {'Tiers' if len(passed) > 1 else 'Tier'} {' and '.join(passed)} had nobody available."

    for index in range(position + 1, len(tiers)):
        person = _person_at(tiers[index], team, holder)
        if person is not None:
            _hand_to(incident, person, author, "escalation",
                     f"{reason}.{skipped()} Escalated to tier {index + 1}: {_full_name(person)}",
                     "escalated", f"escalated to you at tier {index + 1}", at=now, level=index)
            return
        passed.append(str(index + 1))

    incident.assigned_to = None
    incident.status = "open"
    incident.is_unassigned_after_escalation = True
    incident.escalation_level = position + 1
    incident.escalation_timer_started_at = now
    incident.save()
    if not to_administration:
        # The policy just ends. The lead is told, or the administrators when there is no active lead.
        log_event(incident, author, "escalation",
                  f"{reason}.{skipped()} Escalation ran out: this ticket is unassigned and needs attention",
                  old_assignee=holder)
        for person in _lead_or_admins(team):
            if is_lead(person, team):
                action = "Open it and reassign it to a solver on call."
            else:
                action = f"{team.name} has no active lead to reassign it."
            notify(person, incident, "final_escalation",
                   f"{_ticket_label(incident)} ran out of escalation tiers and is unassigned. {action}")
        return

    # The lead ticked Administration on the policy page: it is the last tier.
    # The administrators are told as well as the lead.
    log_event(incident, author, "escalation",
              f"{reason}.{skipped()} Escalated to administration: this ticket is unassigned and needs attention",
              old_assignee=holder)
    lead = team.lead if team.lead is not None and team.lead.is_active else None
    told = f"{_ticket_label(incident)} escalated to administration and is unassigned."
    if lead is not None:
        notify(lead, incident, "administration", f"{told} Open it and reassign it to a solver on call.")
    for admin in _admins():
        if admin == lead:
            continue
        why = f"Nobody on {team.name} started work on it in time."
        if lead is None:
            why += f" {team.name} has no active lead to reassign it."
        notify(admin, incident, "administration", f"{told} {why}")
