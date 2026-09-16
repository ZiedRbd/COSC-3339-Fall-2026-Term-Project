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

## Troubleshooting

```bash
sudo systemctl status campusdesk --no-pager -l
sudo journalctl -u campusdesk -n 50 --no-pager
sudo nginx -t
```

First-time setup and HTTPS are in [`deploy/DEPLOY.md`](../deploy/DEPLOY.md).
