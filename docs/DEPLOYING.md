# Deploying to Production

The live site is **https://campusdesk.duckdns.org**, running on a DigitalOcean droplet at `64.227.3.58`.
The server always runs the `main` branch. Nothing reaches production until it is merged into `main`.

## When to deploy

After a pull request from `dev` into `main` is merged.

## Steps

1. SSH into the droplet:

   ```bash
   ssh ziedrbd@64.227.3.58
   ```

2. Pull the new code and restart the app:

   ```bash
   cd /srv/campusdesk
   sudo git pull
   sudo venv/bin/python manage.py migrate
   sudo venv/bin/python manage.py collectstatic --noinput
   sudo systemctl restart campusdesk
   ```

3. Open https://campusdesk.duckdns.org and confirm the change is live.

## What each step does

| Command | Purpose |
|---|---|
| `git pull` | Downloads the latest `main` |
| `migrate` | Applies any new database migrations. Does nothing if there are none |
| `collectstatic` | Copies updated CSS and JS to the folder nginx serves from. Does nothing if unchanged |
| `systemctl restart campusdesk` | Restarts gunicorn so it loads the new Python code |

Run all four every time. The ones that are not needed finish instantly.

## Rules

- Do not edit files on the server. Edit locally, push, merge to `main`, then pull on the server.
- Do not run `seed` on the server unless the database was reset. It is safe to rerun, but it is not needed.
- The `.env` file on the server holds the secret key and database password. It is not in git. Do not copy it anywhere.

## If something breaks

```bash
sudo systemctl status campusdesk --no-pager -l    # is gunicorn running, and why not
sudo journalctl -u campusdesk -n 50 --no-pager     # last 50 lines of app logs
sudo nginx -t                                      # is the nginx config valid
```

First-time server setup and the HTTPS certificate steps are in [`deploy/DEPLOY.md`](../deploy/DEPLOY.md).
