# ER Diagram

Seven tables. Every line is a foreign key. The same diagram in PlantUML is in [`er-diagram.puml`](er-diagram.puml).

```mermaid
erDiagram
    USER ||--o{ TEAM_MEMBER : "belongs to"
    TEAM ||--o{ TEAM_MEMBER : "has"
    USER o|--o{ TEAM : "leads"
    TEAM o|--o{ SERVICE : "owns"
    SERVICE ||--o{ INCIDENT : "has"
    USER ||--o{ INCIDENT : "reports"
    USER o|--o{ INCIDENT : "assigned to"
    TEAM o|--o{ INCIDENT : "assigned team"
    INCIDENT ||--o{ INCIDENT_UPDATE : "has"
    USER ||--o{ INCIDENT_UPDATE : "writes"
    TEAM ||--o{ SHIFT : "has"
    USER ||--o{ SHIFT : "covers"
    USER ||--o{ SHIFT : "scheduled by"

    USER {
        int id PK
        string username UK
        string email UK
        string password "hashed"
        string first_name
        string last_name
        string role "reporter or solver"
        string bio
        bool is_active
        datetime created_at
    }

    TEAM {
        int id PK
        string name UK
        string description
        int lead_id FK "nullable, the team lead, a solver"
        datetime created_at
    }

    TEAM_MEMBER {
        int id PK
        int user_id FK
        int team_id FK
        datetime joined_at "user_id and team_id are unique together"
    }

    SERVICE {
        int id PK
        string name
        string description
        int owning_team_id FK "nullable"
        string criticality
        bool is_active
        datetime created_at
    }

    INCIDENT {
        int id PK
        string title
        string description
        string building "optional"
        string room "optional"
        int service_id FK
        int reported_by_id FK
        int assigned_to_id FK "nullable"
        int assigned_team_id FK "nullable"
        string status "open, assigned, in_progress, resolved, closed"
        string priority "low, medium, high, critical"
        int escalation_level
        datetime escalated_at "nullable"
        datetime sla_due_at "nullable"
        datetime resolved_at "nullable"
        bool is_deleted
        datetime created_at
        datetime updated_at
    }

    INCIDENT_UPDATE {
        int id PK
        int incident_id FK
        int author_id FK
        string update_type "created, status_change, severity, edit, comment, solver_note, assignment, reassignment, assignment_failed"
        string body
        string old_status "status changes only"
        string new_status "status changes only"
        int old_assignee_id FK "nullable, assignment changes only"
        int new_assignee_id FK "nullable, assignment changes only"
        datetime created_at
    }

    SHIFT {
        int id PK
        int team_id FK
        int solver_id FK
        datetime starts_at
        datetime ends_at "exclusive, belongs to the next shift"
        int created_by_id FK
        datetime created_at
    }
```

## Relationships

| Relationship | Type | Via |
|---|---|---|
| User ↔ Team (membership) | many-to-many | `TEAM_MEMBER` |
| User → Team (lead) | one-to-many, optional | `TEAM.lead_id` |
| Team → Service | one-to-many, optional | `SERVICE.owning_team_id` |
| Service → Incident | one-to-many | `INCIDENT.service_id` |
| User → Incident (reporter) | one-to-many | `INCIDENT.reported_by_id` |
| User → Incident (assignee) | one-to-many, optional | `INCIDENT.assigned_to_id` |
| Team → Incident (assigned team) | one-to-many, optional | `INCIDENT.assigned_team_id` |
| Incident → Incident Update | one-to-many | `INCIDENT_UPDATE.incident_id` |
| User → Incident Update (author) | one-to-many | `INCIDENT_UPDATE.author_id` |
| User → Incident Update (old and new assignee) | one-to-many, optional | `INCIDENT_UPDATE.old_assignee_id`, `INCIDENT_UPDATE.new_assignee_id` |
| Team → Shift | one-to-many | `SHIFT.team_id` |
| User → Shift (solver) | one-to-many | `SHIFT.solver_id` |
| User → Shift (scheduled by) | one-to-many | `SHIFT.created_by_id` |

Incidents are never physically deleted: `is_deleted` hides a ticket and keeps its history. A shift covers `starts_at` up to, but not including, `ends_at`. The database refuses a shift whose end is not after its start.
