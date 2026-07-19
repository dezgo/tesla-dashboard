# Tesla Model Y telemetry stack

TeslaMate (data + Grafana) on the `ai` server (SSD Nodes, 208.87.135.58), plus a
custom Flask app reading the same Postgres DB **read-only**.

```
tesla.appfoundry.cc  -> your Flask dashboard (public, basic auth)

localhost:4000       -> TeslaMate UI  (SSH tunnel only, not published)
localhost:3000       -> Grafana       (SSH tunnel only, not published)
```

### Two stacks, on purpose
| | |
|---|---|
| `docker-compose.yml` | the car stack — Postgres, TeslaMate, Grafana, Mosquitto, Flask. Binds **no** public ports. |
| `proxy/` | the **shared** edge proxy. Caddy, TLS, basic auth. The only thing on 80/443. |

They meet on an external Docker network called `web`. The split exists because
this box is expected to host other sites later: they each join `web` and drop a
file in `proxy/sites/`, rather than being bolted into the car stack. Taking the
dashboard down for maintenance then can't take an unrelated site with it.

`proxy/` isn't tesla-specific and should probably become its own repo once a
second site exists.

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
Two stacks, two env files:

```bash
cp .env.example .env              # app stack: DB passwords, encryption key
cp proxy/.env.example proxy/.env  # edge proxy: hostnames, basic auth, ACME

openssl rand -base64 32                                            # -> TM_ENCRYPTION_KEY
docker run --rm caddy caddy hash-password --plaintext 'yourpass'   # -> BASIC_AUTH_HASH
```
**Double every `$` in the bcrypt hash** when putting it in `proxy/.env`
(`$2a$14$abc…` → `$$2a$$14$$abc…`). Compose interpolates `$` in `.env` values,
so a hash pasted verbatim reaches Caddy truncated at the first `$`, and basic
auth then rejects every password without logging anything useful. Check it with:

```bash
docker compose -f proxy/docker-compose.yml run --rm --no-deps \
  --entrypoint sh caddy -c 'printenv BASIC_AUTH_HASH'
```

## 4. Launch
The shared network has to exist before either stack starts:

```bash
docker network create web         # once per box

docker compose up -d              # app stack (db, teslamate, grafana, flask)
docker compose -f proxy/docker-compose.yml up -d
docker compose -f proxy/docker-compose.yml logs -f caddy   # watch certs issue
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
`proxy/well-known/appspecific/com.tesla.3p.public-key.pem` — Caddy already serves
it at the path Tesla expects, unauthenticated.

## Adding another site later
1. Give the app service `networks: [web]` and a unique alias (service names like
   `flask` collide once two stacks share the network — that's what the
   `tesla-flask` alias is for).
2. Add its hostname + `reverse_proxy <alias>:<port>` in `proxy/sites/<name>.caddy`.
3. `docker compose -f proxy/docker-compose.yml restart caddy`.

## Security notes
- Flask connects as `flask_ro`, a SELECT-only role — an app bug can't corrupt
  TeslaMate's data.
- Postgres, MQTT, TeslaMate and Grafana are **not** reachable from the internet;
  only the proxy's 80/443 are. Keep it that way.
- `.env`, `proxy/.env` and the `.pem` are gitignored. Never commit them —
  **this repo is public.**
- `caddy_data` holds the issued certs. Deleting that volume means re-issuing,
  and Let's Encrypt rate-limits (5 duplicate certs/week).

## Extending the Flask app
`flask-app/app.py` has the DB wiring plus `/api/drives`, `/api/charges`,
`/api/efficiency` and `/api/degradation`. Note that `/api/charges` and
`/api/degradation` return data but nothing on the dashboard renders them yet —
the degradation chart is the obvious next build.

After that: a "where did my range go?" analyzer joining `positions` with
temperature, or a tax logbook that classifies drives by
`start_address`/`end_address`.
