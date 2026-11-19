"""
Overriding a ticket.

An administrator, or the lead of the team a ticket goes to, can force
what the normal buttons refuse: give the ticket to any solver on the
team, move it to any status, or close it from any state. The normal
buttons and their rules are not touched. This is a separate path that
only those two kinds of people can take.

Every override needs a reason. The reason goes on the ticket's timeline
with who did it, as one entry of the kind "override". Because that kind
is its own, an override is never counted as a solver starting or
resolving a ticket.

override_warnings() says which rules an override is about to step over,
so a page can show them before anyone confirms. possible_solvers() lists
who the ticket could be given to. override() makes the change and
returns an Outcome.
"""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .access import can_override, is_admin
from .lifecycle import ALLOWED_TRANSITIONS, STATUS_LABELS
from .models import Incident, User
from .notifications import notify
from .outcome import done, refused
from .scheduling import (MAX_ACTIVE_TICKETS, TAKE_IT, _full_name, _start_clock, _ticket_label, active_ticket_count,
                         assign_all_waiting, assign_now, on_call_solvers, release_to_queue, team_for)
from .timeline import MAX_REASON, clean_reason, log_event

# Somebody holds a ticket in these two statuses, and it counts against their three
HELD = ("assigned", "in_progress")
FINISHED = ("resolved", "closed")
# The steps a ticket takes without an override: the buttons, and the assignment the system makes itself
USUAL_STEPS = {**ALLOWED_TRANSITIONS, "open": ["assigned"]}


def possible_solvers(incident):
    """
    Who an override may give this ticket to: every active solver on the
    team the ticket goes to, and that team's lead, in name order. Being
    off call or already holding three tickets rules nobody out.
    """
    team = team_for(incident)
    if team is None:
        return []
    return list(User.objects.filter(role="solver", is_active=True)
                .filter(Q(teammember__team=team) | Q(pk=team.lead_id))
                .distinct().order_by("first_name", "last_name", "pk"))


def _same_person(one, other):
    return (one.pk if one is not None else None) == (other.pk if other is not None else None)


def _where_it_leads(incident, new_status, new_solver):
    """
    The status and the holder a ticket would end with if these choices
    were applied, or the sentence saying why they cannot be combined.
    Returns (status, holder, problem). A status equal to the ticket's own
    is the same as none given. Giving an Open ticket to a solver, with no
    status named, is what makes it Assigned.
    """
    if new_status is not None and new_status not in STATUS_LABELS:
        return None, None, "Choose one of the five statuses"
    status_changes = new_status is not None and new_status != incident.status
    status = new_status if status_changes else incident.status
    if status == "open" and new_solver is not None:
        if new_status == "open":
            return None, None, "An Open ticket has no solver. Choose Assigned to give it to someone."
        status = "assigned"
    label = STATUS_LABELS[status]
    if status == "open":
        return status, None, None
    if status in FINISHED and status_changes and new_solver is not None:
        return None, None, f"Moving a ticket to {label} does not give it to anyone. Leave the solver out."

    holder = new_solver if new_solver is not None else incident.assigned_to
    if status in HELD and holder is None:
        return None, None, f"A ticket that is {label} needs a solver. Choose who takes it."
    # A newly chosen solver always has to be able to take the ticket. One who
    # already had it only has to when the ticket is going to count against them.
    if new_solver is not None or status in HELD:
        team = team_for(incident)
        if team is None:
            return None, None, "No team handles this ticket's service, so nobody can be given it"
        if holder not in possible_solvers(incident):
            if new_solver is not None:
                return None, None, f"{_full_name(holder)} is not an active solver on {team.name}"
            return None, None, f"{_full_name(holder)} can no longer hold a ticket for {team.name}. Choose who takes it."
    return status, holder, None


def _what_changed(old_status, new_status, old_holder, new_holder):
    """One sentence, with no full stop, for what an override did: the status, the holder, or both."""
    parts = []
    if new_status != old_status:
        parts.append(f"status changed from {STATUS_LABELS[old_status]} to {STATUS_LABELS[new_status]}")
    if not _same_person(old_holder, new_holder):
        if old_holder is None:
            parts.append(f"assigned to {_full_name(new_holder)}")
        elif new_holder is None:
            parts.append(f"taken from {_full_name(old_holder)}")
        else:
            parts.append(f"reassigned from {_full_name(old_holder)} to {_full_name(new_holder)}")
    sentence = " and ".join(parts)
    return sentence[:1].upper() + sentence[1:]


def override_warnings(incident, new_status=None, new_solver=None):
    """
    The rules these choices step over, as sentences to show before anyone
    confirms. Empty when there is nothing to warn about, and also when
    the choices cannot be combined or change nothing, which override()
    refuses.
    """
    status, holder, problem = _where_it_leads(incident, new_status, new_solver)
    if problem:
        return []
    old_status, old_holder = incident.status, incident.assigned_to
    status_changes = status != old_status
    holder_changes = not _same_person(old_holder, holder)
    if not status_changes and not holder_changes:
        return []
    team = team_for(incident)
    sentences = []

    if status_changes and status not in USUAL_STEPS.get(old_status, []):
        sentences.append(f"A ticket does not normally go from {STATUS_LABELS[old_status]} to {STATUS_LABELS[status]}. "
                         f"This skips the usual steps.")
    # Only an Assigned or In Progress ticket is held. A finished one just carries its solver's name.
    lets_go = old_holder is not None and old_status in HELD and holder_changes
    if lets_go:
        sentences.append(f"{_full_name(old_holder)} holds this ticket and will lose it.")
    if status == "open":
        on_call = on_call_solvers(team) if team is not None else []
        # The queue counts tickets after this one is let go, so its old holder has one fewer
        with_room = [solver for solver in on_call
                     if active_ticket_count(solver) - (lets_go and solver == old_holder) < MAX_ACTIVE_TICKETS]
        if team is None:
            sentences.append("No team handles this ticket's service, so it will wait until one does.")
        elif not on_call:
            sentences.append(f"Nobody is on call for {team.name} right now, so the ticket will wait.")
        elif not with_room:
            sentences.append(f"Everyone on call for {team.name} holds {MAX_ACTIVE_TICKETS} tickets, "
                             f"so the ticket will wait in the queue.")
        elif lets_go and with_room[0] == old_holder:
            sentences.append(f"The ticket goes back to the queue. {_full_name(old_holder)} is on call with room, "
                             f"so it can come straight back to them. Choose a solver to give it to someone else.")
        else:
            sentences.append("The ticket goes back to the queue, and whoever on call has room gets it.")
    # From here on the ticket counts against this solver, and it did not before
    if status in HELD and (holder_changes or old_status not in HELD):
        if holder not in on_call_solvers(team):
            sentences.append(f"{_full_name(holder)} is not on call for {team.name} right now.")
        held = active_ticket_count(holder)
        if held >= MAX_ACTIVE_TICKETS:
            sentences.append(f"{_full_name(holder)} already holds {held} tickets. This will be number {held + 1}.")
    if not holder_changes and old_status == "in_progress" and status == "assigned":
        sentences.append(f"{_full_name(holder)} had started work. The ticket will count as not started again "
                         f"and can escalate.")
    if holder_changes and holder is not None and status in FINISHED:
        sentences.append(f"This ticket is {STATUS_LABELS[status]}. Only the name of its solver changes.")
    if status_changes and status in ("in_progress", "resolved"):
        sentences.append("An override is not counted as a solver's work in the analytics.")
    return sentences


@transaction.atomic
def override(incident, by, reason, new_status=None, new_solver=None):
    """
    Force a change on a ticket: a new status, a new solver, or both.
    Closing a ticket from any state is new_status="closed".

    What each status means for who holds the ticket:
    - Open: nobody holds it. It goes back to the queue, which hands it
      out again exactly as it does when a ticket is reopened.
    - Assigned and In Progress: somebody must hold it, the solver given
      or else whoever has it now. An Assigned ticket starts tier 1 again.
    - Resolved and Closed: whoever has it stays on record, and their
      slot is free for a ticket that was waiting.
    With no status given, only the solver changes, and an Open ticket
    becomes Assigned because somebody holds it now.

    Refused, with nothing changed, when the person may not override this
    ticket, the reason is blank or too long, the choices cannot be
    combined, the solver cannot take it, or nothing would change.
    """
    # The minute timer, a solver or another override may be changing this
    # ticket right now. Wait for them to finish, then read it again.
    Incident.objects.select_for_update(of=("self",)).get(pk=incident.pk)
    incident.refresh_from_db()

    if incident.is_deleted:
        return refused(f"Ticket #{incident.pk} was removed. Restore it first.")
    if not can_override(by, incident):
        return refused("Only an administrator, or the lead of the ticket's team, can override a ticket")
    reason = clean_reason(reason)
    if not reason:
        return refused("An override needs a reason")
    if len(reason) > MAX_REASON:
        return refused(f"The reason can be at most {MAX_REASON} characters")
    status, holder, problem = _where_it_leads(incident, new_status, new_solver)
    if problem:
        return refused(problem)
    old_status, old_holder = incident.status, incident.assigned_to
    status_changes = status != old_status
    holder_changes = not _same_person(old_holder, holder)
    if not status_changes and not holder_changes:
        return refused("Nothing would change. Choose a different status or a different solver.")
    team = team_for(incident)

    if status == "open":
        release_to_queue(incident)
    else:
        incident.status = status
        incident.assigned_to = holder
        incident.is_unassigned_after_escalation = False
        if status in HELD:
            incident.assigned_team = team
            # Whoever holds it now gets the whole wait of tier 1 before it escalates
            _start_clock(incident, timezone.now())
        incident.save()

    what = _what_changed(old_status, status, old_holder, holder)
    log_event(incident, by, "override", f"{what}. Reason: {reason}",
              old_status=old_status if status_changes else "", new_status=status if status_changes else "",
              old_assignee=old_holder if holder_changes else None, new_assignee=holder if holder_changes else None)
    _tell_everyone(incident, by, reason, what, old_status, status, old_holder, holder, team)

    if status == "open":
        # The queue decides who gets it next, exactly as when a ticket is reopened
        assign_now(incident, by)
    if old_holder is not None and old_status in HELD and (holder_changes or status not in HELD):
        # The solver who let go has room again for a ticket that was waiting, on any team they cover
        assign_all_waiting()
    return done(f"Ticket #{incident.pk} was overridden. {what}.")


def _tell_everyone(incident, by, reason, what, old_status, status, old_holder, holder, team):
    """
    One notification each, at most, for the people an override concerns:
    the solver who gets the ticket, the solver who had it, the reporter
    when the status changed, and the team's lead when an administrator
    did it. Nobody is told about what they did themselves.
    """
    label = _ticket_label(incident)
    why = f"Reason: {reason}"
    moved = f"was moved from {STATUS_LABELS[old_status]} to {STATUS_LABELS[status]}"
    status_changes = status != old_status
    holder_changes = not _same_person(old_holder, holder)
    already_told = {by.pk}

    def tell(person, message):
        if person is not None and person.pk not in already_told:
            already_told.add(person.pk)
            notify(person, incident, "override", message)

    if holder_changes and holder is not None:
        if status == "assigned":
            tell(holder, f"{label} was given to you by an override. {TAKE_IT}. {why}")
        elif status == "in_progress":
            tell(holder, f"{label} was given to you by an override. It is In Progress, so carry on with the work. {why}")
        else:
            tell(holder, f"{label} is now under your name by an override. It is {STATUS_LABELS[status]}, "
                         f"so there is nothing to do. {why}")
    if old_holder is not None:
        if holder_changes and old_status in FINISHED:
            # A finished ticket was not held, so there is nothing to lose but the name on it
            tell(old_holder, f"{label} is no longer under your name by an override. {why}")
        elif holder_changes:
            tell(old_holder, f"{label} was taken from you by an override. You no longer hold it. {why}")
        elif status == "assigned":
            tell(old_holder, f"{label} {moved} by an override. {TAKE_IT}. {why}")
        else:
            tell(old_holder, f"{label} {moved} by an override. {why}")
    if status_changes:
        who = "an administrator" if is_admin(by) else "the team lead"
        tell(incident.reported_by, f"Your ticket #{incident.pk}, {incident.title}, {moved} by {who}. {why}")
    if team is not None and is_admin(by):
        tell(team.lead, f"{label} was overridden by an administrator: {what[:1].lower() + what[1:]}. {why}")
