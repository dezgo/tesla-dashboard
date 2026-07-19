# Tesla Model Y telemetry stack

TeslaMate (data + Grafana) on the `ai` server (SSD Nodes, 208.87.135.58), plus a
custom Flask app reading the same Postgres DB **read-only**. Caddy fronts the one
public hostname with automatic HTTPS and basic auth.

```
tesla.appfoundry.cc  -> your Flask dashboard (public, basic auth)

localhost:4000       -> TeslaMate UI  (SSH tunnel only, not published)
localhost:3000       -> Grafana       (SSH tunnel only, not published)
```

Only the dashboard is on the internet. TeslaMate's UI is mostly a one-time thing
(authorizing the car), and Grafana is for you, so neither needs a public
hostname — both bind to loopback and you tunnel in:

```bash
ssh -L 4000:localhost:4000 ai     # then open http://localhost:4000
ssh -L 3000:localhost:3000 ai     # then open http://localhost:3000
```

## 1. DNS
One A-record: `tesla` → `208.87.135.58`, in Cloudflare.

**Set it to DNS-only (grey cloud), not proxied.** With the orange cloud on,
Cloudflare intercepts the ACME HTTP-01 challenge and Caddy can never issue a
cert. Wait for it to resolve before starting the stack.

## 2. Server prep
- Open firewall ports 80 and 443 (`sudo ufw allow 80,443/tcp`).
- Docker + the compose plugin are already installed on `ai`.

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
TeslaMate's UI isn't public, so tunnel to it:

```bash
ssh -L 4000:localhost:4000 ai
```

Open `http://localhost:4000`, and follow TeslaMate's flow to authorize against
the Tesla **Fleet API**. Drive around for a day or two, then:
- `https://tesla.appfoundry.cc` → your Flask efficiency chart + last-10-drives.
- Grafana (tunnel to :3000) → the bundled dashboards light up.

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
`flask-app/app.py` has the DB wiring plus `/api/drives`, `/api/charges`,
`/api/efficiency` and `/api/degradation`. Note that `/api/charges` and
`/api/degradation` return data but nothing on the dashboard renders them yet —
the degradation chart is the obvious next build.

After that: a "where did my range go?" analyzer joining `positions` with
temperature, or a tax logbook that classifies drives by
`start_address`/`end_address`.
