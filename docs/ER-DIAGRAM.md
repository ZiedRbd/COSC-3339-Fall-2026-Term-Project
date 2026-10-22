# ER Diagram — Campus IT Help Desk

    TEAM ||--o{ SHIFT : "has"
    USER ||--o{ SHIFT : "covers"
    USER |o--o{ TEAM : "leads"

```mermaid
erDiagram
    SHIFT {
        int id PK
        int team_id FK
        int solver_id FK
        datetime starts_at
        datetime ends_at "exclusive, belongs to the next shift"
        int created_by_id FK
        datetime created_at
    }

    USER ||--o{ TEAM_MEMBER : "belongs to"
    TEAM ||--o{ TEAM_MEMBER : "has"
    TEAM ||--o{ SERVICE : "owns"
    SERVICE ||--o{ INCIDENT : "has"
    USER ||--o{ INCIDENT : "reports"
    USER o|--o{ INCIDENT : "assigned to"
    TEAM o|--o{ INCIDENT : "assigned team"
    INCIDENT ||--o{ INCIDENT_UPDATE : "has"
    USER ||--o{ INCIDENT_UPDATE : "writes"

    USER {
        int id PK
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
        int lead_id FK \"the team lead, a solver\"
        datetime created_at
    }

    TEAM_MEMBER {
        int user_id PK,FK
        int team_id PK,FK
        datetime joined_at
    }

    SERVICE {
        int id PK
        string name
        string description
        int owning_team_id FK
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
        string priority
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
        int old_assignee_id FK "assignment changes only"
        int new_assignee_id FK "assignment changes only"
        datetime created_at
    }
```

## Relationships

| Relationship | Type | Via |
|---|---|---|
| User ↔ Team | many-to-many | `TEAM_MEMBER` |
| Team → Service | one-to-many | `SERVICE.owning_team_id` |
| Service → Incident | one-to-many | `INCIDENT.service_id` |
| User → Incident (reporter) | one-to-many | `INCIDENT.reported_by_id` |
| User → Incident (assignee) | one-to-many, optional | `INCIDENT.assigned_to_id` |
| Team → Incident (assigned team) | one-to-many, optional | `INCIDENT.assigned_team_id` |
| Incident → Incident Update | one-to-many | `INCIDENT_UPDATE.incident_id` |
| User → Incident Update (author) | one-to-many | `INCIDENT_UPDATE.author_id` |
