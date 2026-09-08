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
