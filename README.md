# CampusDesk

CampusDesk is an incident and escalation system for a university campus. Students, faculty, and staff file tickets when something is broken, whether that is a leaking sink, a dead outlet, or Wi-Fi that will not connect. Each ticket is filed against a service, and each service is owned by the team responsible for fixing it. A new ticket is assigned to the solver on call, escalates up the team's own policy when nobody starts work on it, and notifies the people involved in the app and by email.

Live site: https://campusdesk.duckdns.org

Built with Django and PostgreSQL. See [`docs/`](docs/) for the ER diagram and deployment steps.

## Running Locally

```bash
git clone https://github.com/ZiedRbd/COSC-3339-Fall-2026-Term-Project.git
cd COSC-3339-Fall-2026-Term-Project
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
python manage.py migrate
python manage.py seed
python manage.py runserver
```

Open http://127.0.0.1:8000. The `seed` command loads three teams, seven services, seventeen users (six reporters, ten solvers and one administrator), and twenty-four incidents. `python manage.py seed_shifts` adds a week of on-call shifts. `python manage.py escalate` runs one pass of the escalation timer by hand. `python manage.py loadtest` times the incident list with 100, 1000 and 10000 tickets inside a transaction that is rolled back, so it saves nothing, sends no email, and is safe on the server.

Local development uses SQLite. No `.env` file is needed; production settings are read from environment variables only when they are present. Without a mail account in the environment, notification emails are printed in the terminal instead of being sent.

Run the tests with `python manage.py test ops`.

## Project Structure

```
COSC-3339-Fall-2026-Term-Project/
├── manage.py                   Django command entry point
├── requirements.txt            Python dependencies
├── .env.example                Environment variables the server needs
├── config/
│   └── settings.json           Every limit and number the site uses, editable without touching the code
├── campusdesk/                 Project configuration
│   ├── settings.py             Settings, database, static files
│   ├── urls.py                 Top-level URL routing
│   ├── asgi.py                 ASGI entry point, not used by the server
│   └── wsgi.py                 Entry point for gunicorn
├── ops/                        Application code
│   ├── models.py               Database tables
│   ├── views.py                Request handlers
│   ├── forms.py                Form fields and validation
│   ├── urls.py                 Application URL routing
│   ├── scheduling.py           Who is on call, schedule validation, assignment, escalation
│   ├── notifications.py        Writes a notification and sends it by email
│   ├── json_settings.py        Reads and checks config/settings.json when the server starts
│   ├── context_processors.py   Unread notifications for the bell, and the settings, on every page
│   ├── timeline.py             Writes entries to a ticket's timeline
│   ├── buildings.py            Finds a campus building from what somebody typed
│   ├── access.py               Who may do what: who is an administrator, who may override a ticket
│   ├── lifecycle.py            The statuses of a ticket and the moves the normal buttons allow
│   ├── outcome.py              What a rule answers with: whether it happened, and the sentences to show
│   ├── removal.py              Removing and restoring users, teams, services, buildings and tickets
│   ├── overrides.py            Forcing a status or a solver on a ticket, with a reason
│   ├── templatetags/status.py  Shows a status by its label
│   ├── tests/                  Automated tests, one file per purpose
│   ├── apps.py                 Application configuration
│   ├── admin.py                Django admin registration; no models are registered
│   ├── migrations/             Database schema history
│   └── management/commands/
│       ├── seed.py             Loads demo data
│       ├── seed_checkpoint.py  Adds the demo administrator and auditor when they are missing
│       ├── seed_shifts.py      Seeds 24/7 on-call shifts, for a week or up to a chosen day
│       ├── escalate.py         One pass of the escalation timer, run every minute on the server
│       └── loadtest.py         Times the incident list as the number of tickets grows; saves nothing
├── templates/                  HTML pages
│   ├── base.html               Shared layout and navigation
│   ├── home.html
│   ├── services.html
│   ├── login.html
│   ├── register.html
│   ├── profile.html            Profile picture, bio, a reporter's tickets or a solver's teams
│   ├── calendar.html           Weekly on-call calendar
│   ├── schedule.html           A team lead's shift editor
│   ├── shift_table.html        One list of shifts on the schedule page
│   ├── policy.html             A team lead's escalation policy editor
│   ├── 404.html                Shown when an address leads nowhere
│   ├── 403_csrf.html           Shown when a form is sent from a page left open too long
│   ├── 500.html                Shown when the server fails; stands on its own
│   └── incidents/
│       ├── landing.html        Links to file a ticket or view the list
│       ├── list.html           A solver's incident table for their teams, with the severity filter
│       ├── form.html           Create and edit an incident
│       └── detail.html         One incident with its timeline
├── static/
│   ├── css/
│   │   ├── base.css            Colours, type, page layout, top bar, and the notification bell
│   │   ├── components.css      Sheets, buttons, forms, notices, tags, tables, and popups
│   │   ├── incidents.css       The ticket, the incident list, the ticket page, schedule and policy
│   │   ├── profile.css         Profile page, profile picture, and a reporter's tickets
│   │   ├── calendar.css        On-call calendar grid
│   │   ├── pages.css           Home, services, log in, register, and the ticket form
│   │   └── animations.css      The few things that move, and the reduced-motion rule
│   ├── js/
│   │   ├── password.js         Show/hide password and live rule checklist
│   │   ├── incidents.js        Delete confirmation dialog
│   │   ├── filter.js           Severity filtering on the incident list
│   │   ├── transition.js       Confirmation modal for status changes
│   │   ├── schedule.js         Shift form popup and confirmation on the schedule page
│   │   └── notifications.js    Opens and closes the bell's list and lays out each notification
│   └── images/
│       ├── favicon.svg         Browser tab icon
│       └── profile_icon.jpeg   Picture shown until a user uploads their own
├── deploy/
│   ├── gunicorn.service        systemd unit for the application server
│   ├── escalate.service        systemd unit that runs one escalation pass
│   ├── escalate.timer          systemd timer that starts it every minute
│   └── nginx.conf              Reverse proxy configuration
└── docs/
    ├── ER-DIAGRAM.md           Entity relationship diagram
    ├── er-diagram.puml         Same diagram in PlantUML
    ├── er-diagram-sprint4.puml   ER diagram of the changes from Sprint 3 to Sprint 4
    ├── er-diagram-sprint5.puml   ER diagram of the changes from Sprint 4 to Sprint 5
    ├── incident-state-machine.puml   Incident lifecycle states and transitions
    ├── solver-sequence.puml    How a solver moves an assigned incident forward
    ├── assignment-sequence.puml  How a filed ticket is assigned to the solver on call
    ├── escalation-activity.puml  Activity diagram of the escalation process
    ├── TECHNOLOGY.md           Technology choices and reasoning
    └── DEPLOYING.md            Steps to release to the server
```

## Settings

Every limit, number and piece of wording that may need to change lives in `config/settings.json`, grouped by
what it belongs to: tickets, the escalation policy, the on-call schedule, overrides and removals, the auditor,
accounts, the administrator console, notifications, the email server, the site and the building search. Each
setting is named after what it is, for example `max_tickets_a_solver_can_hold` or `reason_min_characters`.

- The file is read once, when the server starts, and kept in memory. After editing it, restart the server.
- It is checked as it is read. A setting that is missing, misspelt, of the wrong kind or out of range stops the
  server from starting, and the message names the setting and says what it must be.
- The pages show the same values the server enforces, because the templates read them from the same file.
- Nothing in the file is secret. Keys and passwords stay in `.env`.

Three kinds of values are deliberately not in the file. Each team's escalation policy, the teams, the services
and the buildings are edited on the site and stored in the database. The statuses, the roles and the moves
between statuses are part of the program. The sizes of database columns need a migration to change.

## Database Relationships

| Relationship | Type | Implemented via |
|---|---|---|
| User ↔ Team | many-to-many | `TeamMember` join table |
| Team → Service | one-to-many, optional | `Service.owning_team` |
| Service → Incident | one-to-many | `Incident.service` |
| User → Incident (reporter) | one-to-many | `Incident.reported_by` |
| User → Incident (assignee) | one-to-many, optional | `Incident.assigned_to` |
| Team → Incident (assigned team) | one-to-many, optional | `Incident.assigned_team` |
| Incident → IncidentUpdate | one-to-many | `IncidentUpdate.incident` |
| User → IncidentUpdate (author) | one-to-many | `IncidentUpdate.author` |
| User → IncidentUpdate (old and new assignee) | one-to-many, optional | `IncidentUpdate.old_assignee`, `IncidentUpdate.new_assignee` |
| User → Team (lead) | one-to-many, optional | `Team.lead` |
| Team → Shift | one-to-many | `Shift.team` |
| User → Shift (solver) | one-to-many | `Shift.solver` |
| User → Shift (scheduled by) | one-to-many | `Shift.created_by` |
| Team → EscalationTier | one-to-many | `EscalationTier.team` |
| User → EscalationTier (named person) | one-to-many, optional | `EscalationTier.escalate_to_user` |
| User → Notification | one-to-many | `Notification.user` |
| Incident → Notification | one-to-many, optional | `Notification.incident` |
| Building → Incident | one-to-many, optional | `Incident.building` |
| User → User, Team, Service, Building, Incident (removed by) | one-to-many, optional | `removed_by` on each of the five models |

A user may belong to one or more teams. Each service is owned by at most one team; a ticket against a service with no team cannot be assigned. Each incident is filed against exactly one service by exactly one reporting user, and may optionally be assigned to a handling user and team. Each incident may accumulate any number of updates, each written by one user.

Nothing is physically deleted. Removing a user, a team, a service or a building sets its `is_active` to false, and deleting a ticket sets `is_deleted`. The row leaves every list and dropdown but its history is kept, and `removed_at` and `removed_by` record when it was removed and by whom. A ticket points at a row of `Building`, the campus list of buildings and residence halls, and keeps in `building_typed` what was typed before that list existed. A ticket filed before the list existed is linked to a building only when what was typed spells out a whole name or short name of it and nothing else but a place inside it, such as a room or a floor; anything less certain stays as the typed text. It can carry an optional `photo` of the problem and the reporter's `rating` of the fix, from 1 to 5. Each escalation entry on a timeline stores the tier it moved the ticket to in `escalated_to_tier`.

Full ER diagram: [`docs/ER-DIAGRAM.md`](docs/ER-DIAGRAM.md)

## Roles and Incident Lifecycle

**Roles.** Every user is a *reporter* or a *solver* (the `role` field, default `reporter`).
- **Reporters** file tickets and add comments. From their profile page they can edit or delete their own tickets until a solver starts work on one. The service a ticket was filed against is fixed once it is routed. They cannot change a ticket's status.
- **Solvers** work the tickets assigned to their team. They move the tickets assigned to them through the lifecycle and add notes; a team lead can move any ticket of the team. They see the full incident list, filtered to their team, and cannot file or delete tickets. Once work starts on a ticket, only the assigned solver can edit its details.
- **Administrators** are users with `is_superuser` set, a flag on the account and not a third `role` value; the seeded one is a reporter. An administrator is notified when a ticket is escalated to administration on a team whose policy has that tier, when a second ticket, and each one after it, starts waiting in a team's queue, and in the lead's place when a team has no active lead. An administrator can open any ticket to read it. The normal buttons on a ticket are still checked for an administrator as for any other user; what an administrator can do beyond them is remove and restore things and override a ticket, described below. The seeded administrator cannot sign in to the Django admin.

Each role sees a different profile page. Any user can upload a profile picture there (JPEG, PNG or WebP, at most 2 MB); it is stored as a file under `media/avatars/`, outside the repository, and can be replaced or removed. A reporter's profile lists the tickets they filed, split into active and closed. A solver's profile lists the teams they belong to and the members of each team.

A reporter's comments and a solver's notes both appear on the ticket timeline, and neither side can edit the other's entries.

**Severity.** Every ticket is filed with one of four severity levels, required at submission: Low, Medium, High, Critical. The level is shown on the incident list and can be filtered there.

**Lifecycle.** A ticket moves through five states in order, with reopening allowed from the end:

```
Open -> Assigned -> In Progress -> Resolved -> Closed
                                          |            |
                                          +--- reopened back to Open ---+
```

Only legal moves are accepted; an illegal move (skipping a step, or going backward without reopening) is rejected with a message explaining why. The system makes one backward move itself: when nobody starts a ticket by the end of its team's policy, the ticket returns from Assigned to Open with nobody assigned, and it is not handed out again until the team lead reassigns it. The full diagram is in [`docs/incident-state-machine.puml`](docs/incident-state-machine.puml).

**Timeline.** Each ticket keeps an automatic, non-editable timeline of everything that happens to it: creation, assignment, a failed assignment (why the ticket is waiting), reassignment, escalation, status changes (old to new), severity changes, detail edits (old to new value), comments, notes, an override, and a removal or restoring by an administrator. Every entry records a user and the time. An entry the system writes by itself is recorded under the user it concerns: the reporter when the ticket is filed, the solver who receives it from the queue, or the solver who held it when it escalated. A reporter reads a plainer version: who has the ticket now, or that it is waiting for a solver. Why it moved from one solver to the next, and the alert that nobody took it in time, are shown to solvers and the administrator only. The timeline is reached by opening a ticket from the profile or incident list. It is stored in the `IncidentUpdate` table.

## On-Call Scheduling and Assignment

**Team leads.** Each team has a `lead`, a column on the Team table pointing at a user. It is not a role value: a solver may lead any number of teams, finding a team's lead is one row read, and a lead does not have to be a member of the team. Only the lead can edit a team's schedule or reassign its tickets.

**Shifts.** A shift is one solver covering one team between two instants. The interval is half open: a shift covers `starts_at` up to, but not including, `ends_at`, so the end instant belongs to the next shift. Shifts are edited on the team's schedule page, and every change is checked against the whole future schedule before it is saved. A save is refused, with a message naming the day and the window, when it would leave a gap between now and the last shift, double book a team, or put one person on two teams at once. It is also refused when it would put a reporter or a non-member on a shift. A shift that ends before it starts, has already ended, or starts before the hour that is running now is refused by the form. A shift is at most 12 hours, and the same solver cannot take two shifts in a row. Editing a shift's start or end moves the neighbouring shift's boundary with it, so the week stays whole in one save.

**Primary and secondary.** Every shift is primary or secondary, chosen when it is added. The rules above are the primary's: a team has exactly one primary at a time, with no gap between now and its last shift. A secondary is optional, so hours without one are fine. A secondary shift is at most 24 hours, a team has one secondary at a time, a person rests 24 hours between two secondary shifts, and nobody is on call twice at the same moment in any role on any team.

**Calendar.** Solvers see a week of cover for every team they are on or lead, one row per team and one column per day. Leads get a link to the schedule and a link to the escalation policy of each team they lead. Reporters and signed-out visitors cannot open it.

**Automatic assignment.** When a ticket is filed, it goes to the primary on call for the team that owns the service, moving from Open to Assigned with an entry on the timeline. A solver holds at most three unfinished tickets (Assigned or In Progress). Once the primary holds three, new tickets go to the secondary, and once both are full a ticket waits, Open and unassigned, with the reason on its timeline. The team lead is notified about the first ticket waiting and the administrator about the second and every one after it. A waiting ticket is handed out, oldest first, as soon as someone on call has room: the check runs every minute on the server and straight away when a ticket is resolved, closed, deleted or reassigned, a shift is added or edited, another ticket is filed or reopened for the team, a solver opens the incident list, or someone opens a ticket that is waiting. A ticket also waits when its service has no team or nobody is on call. Reopening a ticket releases its solver and assigns it again the same way.

**Reassignment.** A team lead can hand an active ticket to the primary or the secondary on call for the team right now, and to nobody else. A solver who already holds three tickets is refused. The timeline records the time, who did it, and the previous and new solver. Assignment and status changes are recorded with timestamps in the `IncidentUpdate` table.

**Seeding.** `python manage.py seed_shifts` fills every team's schedule from now until a week ahead, around the clock, rotating the team's solvers. Pass `--until 2026-11-30` to cover every team to the end of that day instead. A solver who belongs to two teams is never put on call for both in the same hours. It also adds one secondary shift a day, 08:00 to 16:00, wherever the secondary rules allow one. It replaces current and future shifts only. It never takes a ticket from the solver who holds it, and it hands the tickets that were waiting to whoever on call has room. Pass `--short-team Electrical` to stop one team at midnight tonight so the no-cover case can be shown.

## Escalation and Notifications

**Escalation policy.** Each team has its own policy, edited by its lead on the policy page, reached from the calendar and from the schedule. A policy is a list of tiers, each with a wait in minutes. Tier 1 is always the on-call solver who first receives the ticket, so a policy always has at least one tier. A team that has not written a policy has the default one: the on-call solver has 5 minutes, then the lead has 10. Each later tier names either the team lead, which is a role, or one active solver on the team, which is a user. A wait must be a whole number of minutes from 1 to 1440. After the last tier the ticket is marked unassigned, shown in red at the top of the incident list for every solver on the team, and the lead is notified. A lead can tick Administration on the policy page to add it as a last tier with no wait. The ticket then ends the same way, the timeline and the notifications say it was escalated to administration, and the administrator is notified along with the lead. The tick is off until a lead turns it on, and it is stored as one more row of the policy, always the last.

**The timer.** A solver takes responsibility for a ticket by moving it to In Progress. Until then the clock runs from the moment the ticket was assigned, and when the wait of its tier is up the ticket moves to the next tier: the solver changes, the timeline records it, and the new solver is notified. Severity changes every wait: critical tickets wait half as long, high three quarters, medium as written, low twice as long. A tier whose person cannot take the ticket (deactivated, no longer on the team, already holding three tickets, or already the holder) is passed over and named on the timeline. Reopening or reassigning a ticket starts the clock again at tier 1. The check is a scheduled task: a systemd timer runs `python manage.py escalate` once a minute, so it does not depend on anyone having the site open.

**Notifications.** Every notification is a row in the `Notification` table, shown under the bell in the navigation bar, and is also sent by email. A solver is notified when a ticket is assigned to them automatically, reassigned to them by the lead, or escalated to them; the message carries the ticket number, the service, the severity and what to do next. The reporter is notified when work starts on their ticket and when it is resolved, and at no other point. A failed email is logged and never stops the action that caused it; after a failure, email pauses for five minutes so later requests are not slowed down.

## Removing and Restoring

**Nothing is erased.** An administrator, the `is_superuser` flag on a user, removes a user, a team, a service, a building or a ticket. The row is flagged, with who removed it and when, leaves every list and dropdown, and stays on the timelines and in the counts. Restoring it clears the flag. A removed user can no longer log in, is signed out by their next click, and cannot register again because the email is still taken. The rules are in `ops/removal.py`; each one answers with what was done or why it was refused.

**One rule for what people hold.** Nobody is removed until someone else has taken over what they hold. A solver with upcoming shifts, the lead of a team, and a person named in an escalation tier are each refused, with a sentence saying what to hand over first, and each has its own handover: transfer the shifts, appoint a new lead, replace the person in the tier. Taking a solver off one team follows the same rule for that team.

**Transferring shifts.** A removed solver's shifts cannot all go to one person, because nobody may take two shifts in a row. The team's upcoming shifts are walked in order: a shift keeps its solver when it can, and one that cannot goes to the solver the administrator prefers if they are free, otherwise to someone who does not have the next shift, then to whoever has been given the fewest. The result is checked with the same rules as a lead's edit and saved only if the handover adds no problem to the schedule, so the team stays covered around the clock; a problem that was already there does not stop it. A shift the solver is working now is cut at that moment, and their secondary shifts are dropped. A removed solver can no longer be put on a shift.

**Tickets, services and teams.** The tickets a removed solver was working on go back to waiting and the queue hands them out again. A removed service takes no new tickets, and the ones it has carry on. A team cannot be removed while it owns a service or has an unfinished ticket: its services move to another team first and its open tickets follow them into that team's queue. A removed team keeps its members, its policy and the shifts that were worked; the shifts it has not worked yet are dropped, so its solvers are free for other teams. It is restored with no schedule, and only once it has an active lead and every tier that names a person names one who can still take a ticket. An administrator can remove a ticket at any status with a reason, which is written to its timeline. A restored ticket that someone was working on waits for a solver again, with the team that handles its service today. A ticket always goes to the team that owns its service, or stays with its own team when that one is gone.

**Two people at once.** Each rule first waits for anyone else who is changing the same row, then reads it again. Two administrators pressing the same button at the same moment are taken one after the other, and the second is told the thing is already done.

## Override and Closure

**Who.** An administrator can override any ticket. The lead of the team a ticket goes to can override that team's tickets and no others. Nobody else can, and for everyone the normal buttons keep exactly the rules above: an override is a separate path, in `ops/overrides.py`.

**What.** An override forces a new status, a new solver, or both, and closing a ticket from any state is one of them. Every one of the twenty moves between the five statuses is possible. A ticket sent to Open loses its solver and goes back through the queue, exactly as a reopened ticket does. Assigned and In Progress need a solver, the one named or else whoever holds the ticket, and an Assigned ticket starts tier 1 again. Resolved and Closed keep whoever had the ticket on record and free their slot for a ticket that was waiting. With no status named only the solver changes. The solver can be any active solver on the team, or its lead, even one who is off call or already holds three tickets; the queue gives nothing more to a solver who is over three.

**Reason.** Every override needs a reason of at most 500 characters. A blank one is refused and nothing changes. The reason is written to the ticket's timeline in one entry of its own kind, with who did it, the old and new status and the old and new solver. A reporter sees a forced status with its reason, and a change of solver only as who has the ticket now.

**Before and after.** `override_warnings` lists, before anyone confirms, the rules an override is about to step over: a move the normal buttons would refuse, a solver who is off call, a solver who will hold a fourth ticket, a holder who will lose the ticket. After it, the solver who gets the ticket, the solver who had it, the reporter when the status changed, and the team's lead when an administrator did it are each told once, with the reason.

**Analytics.** An override is not a solver's work. Because its timeline entry is its own kind and never a normal status change, a forced In Progress or Resolved does not count toward the time to acknowledge, the time to resolve or the top responders, and overrides can be counted on their own.

## Branching Strategy

The diagram below is an illustrative example of the workflow. Actual branch names and commit order will vary as the project progresses.

```mermaid
%%{init: {'gitGraph': {'mainBranchName': 'main'}}}%%
gitGraph
    commit id: "Initial commit"
    branch dev
    commit id: "Project setup"

    branch feat/models
    commit id: "Database models"
    commit id: "Migrations"

    checkout dev
    branch feat/ui
    commit id: "Base template"
    commit id: "Home and services pages"

    checkout dev
    branch feat/auth
    commit id: "Registration"
    commit id: "Login"

    checkout dev
    merge feat/models id: "Merge models"
    merge feat/ui id: "Merge UI"
    merge feat/auth id: "Merge auth"
    commit id: "Integration testing"

    checkout main
    merge dev id: "Sprint 1 release"
```

**Reading the diagram:** `main` is at the top and only moves when `dev` is merged into it. `dev` is one level down and collects every finished feature. Each `feat/*` branch starts from `dev`, gets its own commits, and comes back into `dev` through a pull request.

| Branch | Purpose | Receives merges from |
|---|---|---|
| `main` | Stable, deployable code. What runs on the server. | `dev` only |
| `dev` | Integration branch. All features are combined and tested here. | `feat/*` and `fix/*` branches via pull request |
| `feat/*`, `fix/*` | One branch per feature or bug fix (e.g. `feat/incident-edit`, `fix/login-redirect`). | — |

**Workflow**

1. Branch off `dev`: `git checkout dev && git pull && git checkout -b feat/your-feature`
2. Commit to the feature branch as work progresses.
3. When the feature works, open a pull request from `feat/your-feature` into `dev`.
4. Once `dev` is stable, open a pull request from `dev` into `main`.

**Rules**

- No direct commits to `main`. Documentation-only changes (`docs/`, `README.md`) are the one exception.
- Commit frequently with descriptive messages.
- Pull `dev` before starting a new feature branch.

## Deployment

The server runs the `main` branch behind nginx and gunicorn with a PostgreSQL database. Steps for pulling a new release onto the server are in [`docs/DEPLOYING.md`](docs/DEPLOYING.md).
