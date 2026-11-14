# Deploying to Production

The server runs the `main` branch. Deploy after a pull request from `dev` into `main` is merged.

## Steps

SSH into the server, then:

```bash
cd /srv/campusdesk
sudo git pull
sudo venv/bin/pip install -r requirements.txt
sudo venv/bin/python manage.py migrate
sudo venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart campusdesk
```

To refresh the demo data, run these before the restart. Both are safe to run again. Tickets they hand to a solver on call notify that solver, by email too when a mail account is configured.

```bash
sudo venv/bin/python manage.py seed
sudo venv/bin/python manage.py seed_shifts
```

## Profile pictures

Uploaded pictures are files in `/srv/campusdesk/media/avatars/`. The application writes them, so the folder belongs to the user gunicorn runs as. Create it once:

```bash
sudo mkdir -p /srv/campusdesk/media
sudo chown -R www-data:www-data /srv/campusdesk/media
```

nginx serves the folder and must accept uploads larger than its 1 MB default. Add these lines to the site's `server` block for port 443, as in `deploy/nginx.conf`, then reload:

```
client_max_body_size 5m;

location /media/ {
    alias /srv/campusdesk/media/;
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

The `media/` folder is not in the repository, so a deploy never touches the pictures. Back it up with the database.

## Email

Notification emails need two lines in `/srv/campusdesk/.env`, then a restart. Without them emails are written to the service log instead of being sent.

```
EMAIL_HOST_USER=the mail account
EMAIL_HOST_PASSWORD=its app password
```

## Escalation timer

Tickets escalate on their own because a systemd timer runs `manage.py escalate` once a minute. Install it once, after the first deploy that contains `deploy/escalate.timer`:

```bash
sudo cp /srv/campusdesk/deploy/escalate.service /srv/campusdesk/deploy/escalate.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now escalate.timer
```

Check it is ticking with `systemctl list-timers escalate.timer` and read its output with `journalctl -u escalate.service -n 20`.

## Troubleshooting

```bash
sudo systemctl status campusdesk --no-pager -l
sudo journalctl -u campusdesk -n 50 --no-pager
sudo nginx -t
```
