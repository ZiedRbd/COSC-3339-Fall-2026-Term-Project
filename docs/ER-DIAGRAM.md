# ER Diagram — Campus IT Help Desk

```mermaid
erDiagram
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
        string password_hash
        string first_name
        string last_name
        string role
        bool is_active
        datetime created_at
    }

    TEAM {
        int id PK
        string name UK
        string description
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
        int service_id FK
        int reported_by_id FK
        int assigned_to_id FK "nullable"
        int assigned_team_id FK "nullable"
        string status
        string priority
        int escalation_level
        datetime escalated_at "nullable"
        datetime sla_due_at "nullable"
        datetime resolved_at "nullable"
        datetime created_at
        datetime updated_at
    }

    INCIDENT_UPDATE {
        int id PK
        int incident_id FK
        int author_id FK
        string update_type
        string body
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
