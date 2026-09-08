# COSC-3339-Fall-2026-Term-Project
## Project Structure

```
COSC-3339-Fall-2026-Term-Project/
├── manage.py               Django entry point
├── requirements.txt
├── campusdesk/             Project configuration
│   ├── settings.py
│   └── urls.py             Top-level URL routing
├── ops/                    Application logic
│   ├── models.py           Database tables
│   ├── views.py            Request handlers
│   ├── urls.py             App URL routing
│   └── migrations/         Auto-generated schema changes
├── templates/              HTML templates
│   ├── base.html           Shared layout and navigation
│   ├── home.html
│   ├── services.html
│   ├── login.html
│   ├── register.html
│   └── incidents/
├── static/css/             Stylesheets
└── docs/                   ER diagram and documentation
```

## Database Relationships

| Relationship | Type | Implemented via |
|---|---|---|
| User ↔ Team | many-to-many | `TeamMember` join table |
| Team → Service | one-to-many | `Service.owning_team` |
| Service → Incident | one-to-many | `Incident.service` |
| User → Incident (reporter) | one-to-many | `Incident.reported_by` |
| User → Incident (assignee) | one-to-many, optional | `Incident.assigned_to` |
| Team → Incident (assigned team) | one-to-many, optional | `Incident.assigned_team` |
| Incident → IncidentUpdate | one-to-many | `IncidentUpdate.incident` |
| User → IncidentUpdate (author) | one-to-many | `IncidentUpdate.author` |

A user may belong to one or more teams. Each service is owned by exactly one team. Each incident is filed against exactly one service by exactly one reporting user, and may optionally be assigned to a handling user and team. Each incident may accumulate any number of updates, each written by one user.

Full ER diagram: [`docs/ER-DIAGRAM.md`](docs/ER-DIAGRAM.md)
