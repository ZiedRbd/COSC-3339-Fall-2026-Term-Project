# Technology Choices

What CampusDesk is built with and why each piece was chosen. Alternatives we considered are noted where they mattered.

## Application framework: Django

Django ships with the parts this project needed most in Sprint 1: a user model, password hashing, session login, form validation, an ORM, and schema migrations. The registration and login requirements were met by writing validation rules rather than authentication plumbing. The ORM lets the same code run against SQLite on laptops and PostgreSQL on the server. Migrations keep every schema change in version control, which matters for a three-person team changing the database at the same time. Python is the language the whole team already knows.

We considered Flask, which would have required adding authentication, sessions, and migrations as separate libraries. We also considered a React front end with a Django API behind it, which would have doubled the codebase and added an API layer for no benefit at this scale.

## Database: PostgreSQL

The server runs PostgreSQL. It enforces foreign keys and unique constraints strictly, handles concurrent users, and is what later sprints will need for escalation timers and reporting queries. SQLite is used for local development because it needs no installation and the ORM hides the difference; settings switch to PostgreSQL automatically when the database variables are present in the environment.

## Application server: gunicorn

Django's built-in `runserver` is single-threaded and documented as development-only. gunicorn is the standard WSGI server for Django. It runs three worker processes, restarts any that crash, and is managed by systemd so it starts on boot. Three workers follows gunicorn's guidance of two per CPU core plus one on a single-core server.

## Web server and reverse proxy: nginx

nginx listens on ports 80 and 443. It serves the static CSS and JavaScript files directly, which is faster than routing them through Python, and forwards every other request to gunicorn over a local socket. It also terminates TLS so gunicorn never handles certificates. nginx in front of gunicorn is the conventional pairing for Django and the one DigitalOcean's own documentation uses.

## Hosting: DigitalOcean droplet

A plain Ubuntu virtual machine, as required by the course. It gives full control over the stack and mirrors how a small production deployment is normally set up.

## HTTPS: DuckDNS and Let's Encrypt

Certificate authorities do not issue TLS certificates for bare IP addresses, so a domain name was required. DuckDNS provides a free subdomain that points at the droplet. certbot obtained a free certificate from Let's Encrypt, rewrote the nginx configuration to use it, and set up automatic renewal. HTTP requests redirect to HTTPS, so credentials are never sent in plain text.

## Configuration: environment variables

The secret key, debug flag, allowed hosts, and database credentials are read from a `.env` file that exists only on the server and is excluded from version control. The same codebase behaves differently per machine without any code changes. An `.env.example` in the repository documents the variable names.

## Front end: Django templates

Pages are rendered server-side with Django templates and styled with a single stylesheet. A base template holds the navigation bar and shared layout; each page extends it. Two small JavaScript files handle the show/hide password toggle, the live password rule checklist, and the delete confirmation dialog. No front-end framework was needed for the pages in scope.
