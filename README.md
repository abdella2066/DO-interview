# Feature Flag Service

A REST API for feature flags: create flags, turn them on or off globally, for a percentage of users, or for individual users, and evaluate them per user, with a cache in front of Postgres and an audit log of every change.

Python 3.12, FastAPI, SQLAlchemy 2 (async) with psycopg 3, Alembic, PostgreSQL, and Valkey (Redis-compatible). A GitHub Actions pipeline tests every change and deploys `main` to DigitalOcean App Platform.

- **Live API:** https://feature-flags-ly8dk.ondigitalocean.app (send the `X-API-Key` header; `/healthz` and `/readyz` are public)
- **Interactive API docs:** `/docs` (Swagger UI) on any running instance
- **Architecture diagrams:** [docs/architecture.md](docs/architecture.md) (deployment, request lifecycle, read path, write path)

## How evaluation works

Every flag has a **global state** (`enabled`). It's set when the flag is created (the "default state", off unless you say otherwise) and changed with `PATCH`. An enabled flag can be limited to a **rollout percentage** of users (0-100, default 100). Individual users can also have a **per-user override**.

Evaluating a flag for a user:

1. Unknown flag: `404 FLAG_NOT_FOUND`.
2. The user has an override: the override's value, with `reason: "USER_OVERRIDE"`.
3. The flag is disabled globally: `false`, with `reason: "GLOBAL"`, whatever the rollout percentage.
4. The rollout percentage is 100: `true`, with `reason: "GLOBAL"`.
5. Otherwise: `true` only if the user's bucket is below the rollout percentage, with `reason: "ROLLOUT"`.

Overrides are explicit exceptions, so they win in both directions: beta testers can see a flag that's off for everyone else, and a customer who opted out keeps it off while it's on for everyone. User IDs are opaque strings from your system and are case-sensitive.

A user's bucket is a number from 0 to 99: the first 8 bytes of `sha256("{flag_key}:{user_id}")`, read as a big-endian integer, modulo 100. It's the same on every request, instance, and deploy, so a user doesn't flip between on and off. Raising the percentage only adds users (everyone who's in at 10% is still in at 50%), and lowering it only removes them. Because the flag key is part of the hash, each flag picks its own users: the 10% who get one flag aren't the same 10% who get the next.

## API

All `/api/v1` endpoints need an `X-API-Key` header. The health probes are public. Writes can also send an optional `X-Actor` header naming who made the change, which is stored in the [audit log](#audit-log).

| Method | Path | What it does | Success |
|---|---|---|---|
| `POST` | `/api/v1/flags` | Create a flag, optionally with a rollout percentage | `201` + `Location` |
| `GET` | `/api/v1/flags?limit=50&offset=0` | List flags, newest first | `200` |
| `GET` | `/api/v1/flags/{key}` | Get one flag | `200` |
| `PATCH` | `/api/v1/flags/{key}` | Update name, description, or rollout percentage, or enable/disable globally | `200` |
| `DELETE` | `/api/v1/flags/{key}` | Delete a flag and its overrides | `204` |
| `PUT` | `/api/v1/flags/{key}/overrides/{user_id}` | Enable/disable for one user | `201` created, `200` replaced |
| `GET` | `/api/v1/flags/{key}/overrides` | List a flag's overrides | `200` |
| `DELETE` | `/api/v1/flags/{key}/overrides/{user_id}` | Remove an override | `204` |
| `GET` | `/api/v1/flags/{key}/evaluate?user_id=...` | Evaluate for a user; `X-Cache: HIT` or `MISS` | `200` |
| `GET` | `/api/v1/users/{user_id}/flags` | Evaluate every flag for a user in one call (for SDKs loading a page) | `200` |
| `GET` | `/api/v1/flags/{key}/audit?limit=50&offset=0` | A flag's change history, newest first; kept after the flag is deleted | `200` |
| `GET` | `/healthz` | Liveness: the process is up | `200` |
| `GET` | `/readyz` | Readiness: Postgres answers; cache reported as `ok` or `degraded` | `200` / `503` |

### Errors and validation

Every error uses one shape, and the `request_id` matches the `X-Request-ID` response header and the log line:

```json
{"error": {"code": "FLAG_ALREADY_EXISTS", "message": "Flag 'new-checkout' already exists", "details": null, "request_id": "4f1c..."}}
```

| Status | Code | When |
|---|---|---|
| 400 | `MALFORMED_JSON` | The body isn't valid JSON |
| 401 | `UNAUTHORIZED` | Missing or wrong `X-API-Key` |
| 404 | `FLAG_NOT_FOUND`, `OVERRIDE_NOT_FOUND`, `NOT_FOUND` | Unknown flag, override, or route |
| 405 | `METHOD_NOT_ALLOWED` | Wrong HTTP method for the path |
| 409 | `FLAG_ALREADY_EXISTS` | Creating a key that exists (enforced by a unique constraint, so it's race-safe) |
| 422 | `VALIDATION_ERROR` | Field-level problems, listed in `details` |
| 503 | `SERVICE_UNAVAILABLE` | Postgres is unreachable, or a query ran past `DATABASE_TIMEOUT_SECONDS` |
| 500 | `INTERNAL_ERROR` | Anything unexpected; logged with the request ID, no stack trace returned |

Validation rules:

- `key`: 1-64 characters: lowercase letters, digits, `-` and `_`, starting with a letter or digit. Keys can't be changed after creation.
- `name`: 1-100 characters after trimming whitespace. `description`: up to 500 characters, or `null`.
- `user_id`: 1-128 characters from `A-Z a-z 0-9 . _ : @ + -`.
- `enabled`: must be a real JSON boolean. `"true"`, `"yes"`, and `1` are rejected.
- `rollout_percentage`: a JSON integer from 0 to 100, default 100. `"50"`, `50.5`, `50.0`, `true`, and `null` are rejected. The database enforces the same range with a `CHECK` constraint.
- Unknown fields are rejected, so a typo like `"enable": true` fails loudly instead of silently doing nothing.
- `PATCH` needs at least one field, and `name`, `enabled`, and `rollout_percentage` can't be set to `null`.
- `limit` is 1-100 and `offset` is 0 or more.
- `X-Actor` (optional header): 1-100 printable ASCII characters. Header values arrive as raw bytes that the server decodes as Latin-1, so a UTF-8 name would be stored garbled; it's rejected instead. The header is validated on every `/api/v1` request, but only writes record it.

### Try it with curl

```bash
export API=http://localhost:8080 KEY=local-dev-key   # or the live URL and the production API key

# Create a flag (off for everyone by default)
curl -s -X POST $API/api/v1/flags -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"key": "new-checkout", "name": "New checkout", "description": "Redesigned checkout flow"}'

# Turn it on for one beta tester
curl -s -X PUT $API/api/v1/flags/new-checkout/overrides/beta-tester \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{"enabled": true}'

# Evaluate: true for the tester (USER_OVERRIDE), false for everyone else (GLOBAL).
# -i shows the X-Cache header: MISS the first time, HIT after that.
curl -si "$API/api/v1/flags/new-checkout/evaluate?user_id=beta-tester" -H "X-API-Key: $KEY"
curl -si "$API/api/v1/flags/new-checkout/evaluate?user_id=someone-else" -H "X-API-Key: $KEY"

# Every flag for one user in a single call
curl -s $API/api/v1/users/beta-tester/flags -H "X-API-Key: $KEY"

# Enable it for 25% of users (reason ROLLOUT; each user's result stays the same),
# recording who made the change
curl -s -X PATCH $API/api/v1/flags/new-checkout \
  -H "X-API-Key: $KEY" -H "X-Actor: alice@example.com" -H "Content-Type: application/json" \
  -d '{"enabled": true, "rollout_percentage": 25}'

# Then for everyone
curl -s -X PATCH $API/api/v1/flags/new-checkout \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{"rollout_percentage": 100}'

# Who changed what, newest first
curl -s $API/api/v1/flags/new-checkout/audit -H "X-API-Key: $KEY"
```

## Caching

- **What's cached:** one snapshot per flag (global state, rollout percentage, and all of its overrides) under `ff:flag:v2:{key}`, with a TTL of `CACHE_TTL_SECONDS` (60 by default). Evaluation is computed in-process from the snapshot, so one entry serves every user of that flag. `v2` is the snapshot format's version (see design decisions).
- **Reads** are cache-aside: try the cache, otherwise load from Postgres and store the snapshot.
- **Writes** commit to Postgres first and then delete the snapshot, so the next read rebuilds it from the source of truth.
- **Backends:** Valkey or Redis when `CACHE_URL` is set, shared by every instance so one invalidation reaches all of them. Without it, an in-memory cache per process, which is only correct with a single instance.
- **Fail-open:** if the cache errors or times out (0.5s, no retries), the request is served from Postgres and a warning is logged.

## Audit log

Every change to a flag or its overrides writes one row to `flag_audit_events`. `GET /api/v1/flags/{key}/audit` returns them newest first as `{"items": [{"action", "actor", "details", "created_at"}], "total", "limit", "offset"}`.

| Action | Written by | `details` |
|---|---|---|
| `flag.created` | `POST /api/v1/flags` | The initial `name`, `description`, `enabled`, and `rollout_percentage` |
| `flag.updated` | `PATCH /api/v1/flags/{key}` | Only the fields whose value changed, with their new values |
| `flag.deleted` | `DELETE /api/v1/flags/{key}` | `{}` |
| `override.set` | `PUT /api/v1/flags/{key}/overrides/{user_id}` | `user_id` and `enabled` |
| `override.deleted` | `DELETE /api/v1/flags/{key}/overrides/{user_id}` | `user_id` |

- **Written in the same transaction as the change,** before the commit, so the two are saved or rolled back together. A rejected write (a duplicate key, an unknown flag) leaves no event, and if the audit insert fails, the change is rolled back too. A `PATCH` that changes nothing writes no event.
- **History outlives the flag.** Events reference the flag by key, not by a foreign key, so deleting a flag keeps its history, and a flag re-created with the same key continues it. A key with no history returns an empty list, not a 404.
- **The actor is self-reported.** It's the `X-Actor` header as sent, or `null` without one. With one shared API key, the service can't tell who's really calling, so treat the actor as a label the caller chose, not a verified identity.

## Running locally

You need [OrbStack](https://orbstack.dev) (or Docker Desktop), [uv](https://docs.astral.sh/uv/), and `make`.

```bash
make up        # Postgres 17 + Valkey 8, runs migrations, starts the API on http://localhost:8080
make install   # creates .venv with Python 3.12 and the dev dependencies
make test      # runs the test suite against the Postgres container
make lint      # ruff lint + format check
make down      # stops the containers (docker compose down -v also wipes the data)
```

To run the API on your machine with auto-reload instead of in a container: `cp .env.example .env`, run `make up` for Postgres and Valkey, then `make migrate` and `make run` (port 8000).

`docker compose` mirrors production: a one-shot `migrate` container runs `alembic upgrade head`, and the API container starts only after it succeeds.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `development` | `development`, `test`, or `production`. Production refuses to start without `API_KEY`. |
| `DATABASE_URL` | local Postgres | `postgres://` and `postgresql://` URLs (as DigitalOcean provides them) are rewritten to use the psycopg driver. |
| `DATABASE_TIMEOUT_SECONDS` | `5` | 1-60. Caps connecting, waiting for a pooled connection, and every SQL statement (Postgres `statement_timeout`). A request that hits it returns 503. |
| `CACHE_URL` | unset | `redis://` or `rediss://` URL for Valkey/Redis. Unset means the in-memory cache. |
| `CACHE_TTL_SECONDS` | `60` | 1-3600 |
| `API_KEY` | unset | Clients send it in the `X-API-Key` header. Unset disables auth (development only). |
| `LOG_LEVEL` | `INFO` | Logs are JSON, one line per request with its request ID. |

## Testing

```bash
make test                                         # in-memory cache variants only
TEST_CACHE_URL=redis://localhost:6379/1 make test  # also runs every API test against Valkey (CI does this)
```

The suite has 252 tests:

- **Unit:** evaluation precedence, rollout bucketing (determinism, monotonicity, distribution, and independence across flags), snapshot serialization, in-memory cache TTL and eviction (with a fake clock), Redis fail-open (including a check that it fails fast), and config parsing.
- **Integration:** FastAPI's `TestClient` against real Postgres, migrated with the real Alembic migrations and truncated before each test. Covers every endpoint and status code, the validation rules above, API key auth, the error envelope, request IDs, a database outage (503), cache hits and misses, and invalidation after every kind of write. The audit log tests cover each action's event, that rejected or failed writes leave no event, and that a failed audit insert rolls back its change. A few tests check the rules the database enforces on its own: the rollout default and range.
- Every API test runs twice: once with the in-memory cache and once with real Valkey.

## CI/CD and deployment

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every pull request and every push to `main`:

1. **lint:** `ruff check` and `ruff format --check`.
2. **test:** Postgres and Valkey service containers, then `alembic upgrade head && alembic check` (fails if the models and migrations drift; `migrations/env.py` enables Alembic's opt-in plugin so named `CHECK` constraints are compared too), then `pytest` with coverage.
3. **docker:** builds the production image.
4. **deploy** (pushes to `main` only, after the first three pass): `digitalocean/app_action` applies [`.do/app.yaml`](.do/app.yaml). App Platform builds the `Dockerfile`, runs the `migrate` job (`alembic upgrade head`) before the new version starts, then rolls it out behind the `/readyz` health check. The job waits and fails if the deployment fails.

The App Platform spec defines one `api` service (Dockerfile build, port 8080, `/readyz` health check), a `PRE_DEPLOY` `migrate` job, and a dev PostgreSQL database whose connection string App Platform injects as `DATABASE_URL`. The pipeline needs two GitHub repo secrets: `DIGITALOCEAN_ACCESS_TOKEN` (to deploy) and `API_KEY` (passed to the app as an encrypted env var).

App Platform only grants a dev database's user permission to create tables after a deployment succeeds, so the `migrate` job must not be in the same deployment that creates a dev database. This app's first deployment was cancelled partway through (a new push cancelled its run), which left the dev database without that permission, and the `migrate` job then failed with `permission denied for schema public`. The fix was DigitalOcean's documented one: remove the dev database and deploy, re-create it and deploy, then re-enable the `migrate` job. The workflow now queues runs on `main` instead of cancelling them.

Deploying somewhere new: fork, add the two secrets, change `repo_clone_url` in `.do/app.yaml`, and push to `main`. The first run creates the app.

## Design decisions and trade-offs

- **Overrides beat the global state.** It's the simplest rule to explain and matches how teams use per-user toggles (beta testers, opt-outs). The trade-off: disabling a flag globally doesn't switch off users with an explicit `true` override. A separate kill switch would handle emergencies (see next steps).
- **Rollouts come after the global switch.** The order is override, then `enabled: false`, then the percentage, so turning a flag off still turns it off for everyone without an override, whatever the percentage. At 100% the reason stays `GLOBAL`, so flags that existed before rollouts behave exactly as they did.
- **Hash-based buckets instead of stored assignments.** Hashing `flag_key:user_id` needs no storage, gives every instance the same answer, and can be computed from the cached snapshot. Reading 64 bits of the hash modulo 100 skews the buckets by about one part in 10^17, which is negligible. Changing the formula would reshuffle every live rollout, so a unit test pins one known bucket.
- **Versioned cache keys.** The snapshot key includes a format version (`ff:flag:v2:{key}`), bumped whenever the snapshot's fields change. During a rolling deploy, old and new instances share Valkey. Old code can't parse a snapshot with a field it doesn't know (its evaluations of that flag would fail with a 500), and new code reading an old snapshot would treat every flag as a 100% rollout. With separate keys, each version reads only snapshots it wrote, and old entries expire after the TTL. The trade-off: during the deploy, a write handled by one version doesn't invalidate the other version's entry, so the other version can serve a stale snapshot for up to the TTL.
- **Audit events share the change's transaction.** An event never describes a change that was rolled back, and a committed change never lacks its event. Writing the event after the commit, or to a separate log stream, could lose events on a crash or record changes that didn't happen. The cost is one extra `INSERT` per write.
- **Audit history keyed by flag key, not a foreign key.** A foreign key would force a choice between blocking flag deletes and cascading the history away. Keying by the flag key keeps the history, at the cost of no referential check (the service only writes keys it just changed).
- **Self-reported actor.** With a single shared API key there's no caller identity to record, so the `X-Actor` header is the best available signal. It's validated for shape (length, printable ASCII), not truth. Per-client API keys would give the audit log a verified actor (see next steps).
- **Cache per flag, not per user.** One entry per flag keeps invalidation to a single `DEL` and serves every user, the same model client-side flag SDKs use. It gets expensive for flags with very large override lists. At that scale I'd move to segments or rules, or cache overrides per user.
- **Invalidate after commit, with a TTL as the backstop.** Correct in the common case. A rare race and failed deletes during a cache outage are bounded by the TTL rather than eliminated.
- **Fail-open cache.** Availability over latency: a Valkey outage makes requests slower, not failed.
- **404 for unknown flags on evaluate,** rather than `enabled: false`. The API reports what it knows, and clients or SDKs decide their own safe default (normally off).
- **Race-safe writes in the database.** Duplicate keys are caught by a unique constraint (409), and overrides use an atomic `INSERT ... ON CONFLICT DO UPDATE`.
- **Offset pagination and a single API key** keep the surface small. Cursor pagination and per-client scoped keys are the upgrade path.
- **App Platform dev database.** Quick to provision but single-node without backups. Production would use a managed PostgreSQL cluster (`production: true` in the spec).

## Next steps

- Kill switch that overrides everything, for incident response.
- Segments and targeting rules.
- Cache the all-flags-for-a-user endpoint (today it's one uncached SQL query), and paginate it for accounts with many flags.
- Environments (dev, staging, prod).
- Per-client API keys with scopes, which would also give the audit log a verified actor, and rate limiting.
- A retention policy for the audit log, which grows without limit today.
- Metrics and tracing (Prometheus or OpenTelemetry), including the cache hit ratio.
- Managed Valkey in production and multiple instances; stampede protection for hot keys.

## Project layout

```text
app/
  main.py          app factory: lifespan (engine + cache), middleware, error handlers, routers
  config.py        settings from environment variables
  db.py            async engine, sessions, database health check
  models.py        flags, flag_overrides, and flag_audit_events tables
  schemas.py       request/response models and validation rules
  errors.py        domain errors and the JSON error envelope
  repository.py    all SQL
  evaluation.py    pure evaluation rules and rollout bucketing
  cache.py         cache interface, in-memory and Valkey/Redis backends
  service.py       business logic, cache-aside reads, invalidation, audit events
  dependencies.py  dependency injection, the API key check, and the X-Actor header
  middleware.py    request IDs and JSON logging
  api/             routes: health, flags, overrides, evaluate, audit
migrations/        Alembic migrations
tests/             unit and integration tests
docs/              architecture diagrams
```
