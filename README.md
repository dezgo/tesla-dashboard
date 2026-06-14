# Tesla Model Y telemetry stack

TeslaMate (data + Grafana) on your DigitalOcean droplet, plus a custom Flask app
reading the same Postgres DB **read-only**. Everything sits behind Caddy with
automatic HTTPS and basic auth.

```
tesla.appfoundry.cc    -> TeslaMate UI   (basic auth)
grafana.appfoundry.cc  -> Grafana        (Grafana's own login)
dash.appfoundry.cc     -> your Flask app (basic auth)
```

## 1. DNS
Add three A-records pointing at the droplet's public IP:
`tesla`, `grafana`, `dash` → `<droplet-ip>`. Wait for them to resolve before
starting Caddy (it needs them live to issue certs).

## 2. Droplet prep
- Open firewall ports 80 and 443.
- Install Docker + the compose plugin.

## 3. Configure
```bash
cp .env.example .env
# fill in strong passwords. Then generate the two computed values:

openssl rand -base64 32                                            # -> TM_ENCRYPTION_KEY
docker run --rm caddy caddy hash-password --plaintext 'yourpass'   # -> BASIC_AUTH_HASH
```
Put the bcrypt hash in `.env` as-is. (In `docker-compose`/Caddy env, a literal
`$` in the hash is fine because it's passed through, not shell-expanded.)

## 4. Launch
```bash
docker compose up -d
docker compose logs -f caddy      # watch certs get issued
```

## 5. Connect the car
Open `https://tesla.appfoundry.cc`, sign in, and follow TeslaMate's flow to
authorize against the Tesla **Fleet API**. Drive around for a day or two, then:
- Grafana → the bundled dashboards light up.
- `https://dash.appfoundry.cc` → your Flask efficiency chart + last-10-drives.

### Optional: sending commands (not just reading)
Newer cars need signed commands via Tesla's Vehicle Command protocol. If you go
there, drop your public key at
`well-known/appspecific/com.tesla.3p.public-key.pem` — Caddy already serves it at
the path Tesla expects, unauthenticated.

## Security notes
- Flask connects as `flask_ro`, a SELECT-only role — an app bug can't corrupt
  TeslaMate's data.
- Postgres and MQTT are **not** published to the host; only Caddy's 80/443 are
  exposed. Keep it that way.
- `.env` and the `.pem` are gitignored. Never commit them.

## Extending the Flask app
`flask-app/app.py` has the DB wiring + three endpoints. Good next builds:
battery-degradation curve from `charging_processes`, a "where did my range go?"
analyzer joining `positions` with temperature, or a tax logbook that classifies
drives by `start_address`/`end_address`.
