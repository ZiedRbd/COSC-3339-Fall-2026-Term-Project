# Deploying to the droplet

Ubuntu, PostgreSQL, gunicorn, nginx. The app lives in `/srv/campusdesk`.

## First time

```bash
apt update && apt install -y python3-venv python3-pip postgresql nginx git
sudo -u postgres psql -c "CREATE USER campusdesk WITH PASSWORD 'choose-a-password';"
sudo -u postgres psql -c "CREATE DATABASE campusdesk OWNER campusdesk;"

git clone https://github.com/ZiedRbd/COSC-3339-Fall-2026-Term-Project.git /srv/campusdesk
cd /srv/campusdesk
python3 -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env        # real secret key, DEBUG=False, droplet IP, db password

venv/bin/python manage.py migrate
venv/bin/python manage.py seed
venv/bin/python manage.py collectstatic --noinput
chown -R www-data:www-data /srv/campusdesk

cp deploy/gunicorn.service /etc/systemd/system/campusdesk.service
systemctl daemon-reload && systemctl enable --now campusdesk

cp deploy/nginx.conf /etc/nginx/sites-available/campusdesk
ln -sf /etc/nginx/sites-available/campusdesk /etc/nginx/sites-enabled/campusdesk
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx
ufw allow 'Nginx Full'
```

## HTTPS

Point a domain at the droplet (DuckDNS works), add it to `ALLOWED_HOSTS` in `.env`, then:

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d campusdesk.duckdns.org
systemctl restart campusdesk
```

Certbot rewrites the nginx config for port 443 and renews the certificate automatically.

## Every update

See [`docs/DEPLOYING.md`](../docs/DEPLOYING.md).
