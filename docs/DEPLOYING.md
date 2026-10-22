# Deploying to Production

The server runs the `main` branch. Deploy after a pull request from `dev` into `main` is merged.

## Steps

SSH into the server, then:

```bash
cd /srv/campusdesk
sudo git pull
sudo venv/bin/python manage.py migrate
sudo venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart campusdesk
```

To refresh the demo data, run these before the restart. Both are safe to run again.

```bash
sudo venv/bin/python manage.py seed
sudo venv/bin/python manage.py seed_shifts
```

## Troubleshooting

```bash
sudo systemctl status campusdesk --no-pager -l
sudo journalctl -u campusdesk -n 50 --no-pager
sudo nginx -t
```
