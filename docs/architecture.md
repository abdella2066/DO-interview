# Architecture

Four views of the service: how it's deployed, what happens to every request, how an evaluation is served (the hot path), and how writes record an audit event and keep the cache correct.

## 1. System and deployment

```mermaid
flowchart LR
    Dev[Developer] -->|git push| Repo[GitHub repo]
    Repo --> CI["GitHub Actions: lint, test, docker build"]
    CI -->|"deploy job: main only, after all checks pass"| Build
    subgraph platform [DigitalOcean App Platform]
        Build["Build image from Dockerfile"] --> Migrate["PRE_DEPLOY job: alembic upgrade head"]
        Migrate --> Service["api service: FastAPI on uvicorn, port 8080"]
    end
    Clients["Clients and SDKs"] -->|"HTTPS with X-API-Key"| Service
    Service --> Postgres[("PostgreSQL: source of truth")]
    Migrate --> Postgres
    Service -.->|"CACHE_URL set"| Valkey[("Valkey: shared cache")]
```

- **Postgres** is the source of truth for flags, overrides, and the audit log. Schema changes ship as Alembic migrations, run by a `PRE_DEPLOY` job before new code takes traffic.
- **Valkey** is optional. With `CACHE_URL` unset, each process uses its own in-memory cache, which is only correct with a single instance.
- **App Platform** routes traffic only to instances whose health check passes, and replaces instances one at a time on deploy.

## 2. Request lifecycle

The order of checks below was verified against the running container: an unknown route is 404 even without an API key, malformed JSON is 400 before the key is checked, and a missing key is 401 before field validation. The `X-Actor` header, added later, is validated in the same step as the path, query, and body; a test checks that a missing key is still a 401 first.

```mermaid
flowchart TD
    Request["HTTP request"] --> Middleware["Middleware: assign X-Request-ID, start timer"]
    Middleware --> Route{"Route and method match?"}
    Route -->|no| RouteError["404 NOT_FOUND or 405 METHOD_NOT_ALLOWED"]
    Route -->|yes| Parse{"JSON body parses?"}
    Parse -->|no| Malformed["400 MALFORMED_JSON"]
    Parse -->|yes| Auth{"X-API-Key valid?"}
    Auth -->|no| Unauthorized["401 UNAUTHORIZED"]
    Auth -->|yes| Validate{"Path, query, headers, body valid?"}
    Validate -->|no| Invalid["422 VALIDATION_ERROR with field details"]
    Validate -->|yes| Handler["Route handler: app/api"]
    Handler --> Service["FlagService: app/service.py"]
    Service --> Outcome{"Result"}
    Outcome -->|ok| Success["200, 201, or 204"]
    Outcome -->|"flag or override missing"| Missing["404 FLAG_NOT_FOUND or OVERRIDE_NOT_FOUND"]
    Outcome -->|"duplicate key"| Conflict["409 FLAG_ALREADY_EXISTS"]
    Outcome -->|"database unreachable"| Unavailable["503 SERVICE_UNAVAILABLE"]
```

Every response, success or error, passes back through the middleware, which adds the `X-Request-ID` header and writes one JSON log line (method, path, status, duration, request ID). Errors all use one envelope, built in `app/errors.py`:

```json
{"error": {"code": "FLAG_NOT_FOUND", "message": "Flag 'x' does not exist", "details": null, "request_id": "..."}}
```

## 3. Evaluation read path (cache-aside)

```mermaid
sequenceDiagram
    participant C as Client
    participant A as Evaluate route
    participant S as FlagService
    participant K as Cache
    participant D as PostgreSQL
    C->>A: GET /api/v1/flags/new-checkout/evaluate?user_id=u1
    A->>S: evaluate("new-checkout", "u1")
    S->>K: GET ff:flag:v2:new-checkout
    alt cache hit
        K-->>S: snapshot JSON
    else cache miss, or cache unreachable (fail-open)
        S->>D: SELECT the flag by key
        Note over S,D: Unknown flag: 404, and nothing is cached
        S->>D: SELECT user_id, enabled FROM flag_overrides
        S->>K: SET ff:flag:v2:new-checkout with TTL 60s
    end
    S->>S: evaluate(snapshot, "u1"): override, else off switch, else rollout
    S-->>A: evaluation and cache_hit
    A-->>C: 200 with enabled and reason, plus X-Cache HIT or MISS
```

- The cached unit is the whole flag (global state, rollout percentage, and its overrides), so one entry serves every user of that flag. Evaluation itself is a pure function in `app/evaluation.py`.
- `evaluate()` applies a fixed precedence. The user's override wins (`USER_OVERRIDE`). Otherwise a disabled flag is off (`GLOBAL`), and an enabled flag at a 100% rollout is on (`GLOBAL`). Otherwise the flag is on only when the user's bucket is below the rollout percentage (`ROLLOUT`). The bucket is `sha256("{flag_key}:{user_id}")` reduced to 0-99, so it needs no stored state and every instance computes the same answer.
- The `v2` in the key is the snapshot format's version. It changes whenever the snapshot's fields change, so instances running different releases during a deploy never read each other's snapshots.
- If the cache is down, reads fall through to Postgres after at most 0.5s (no retries), so a cache outage costs latency, not errors.
- `GET /api/v1/users/{user_id}/flags` (every flag for one user) skips the cache: it's one `LEFT JOIN` query from flags to that user's overrides, fed through the same `evaluate()` function.

## 4. Write path and invalidation

```mermaid
sequenceDiagram
    participant C as Client
    participant S as FlagService
    participant D as PostgreSQL
    participant K as Cache
    C->>S: PATCH /api/v1/flags/new-checkout with enabled true
    S->>D: UPDATE flags SET enabled = true
    S->>D: INSERT INTO flag_audit_events (flag.updated, actor, changed fields)
    S->>D: COMMIT
    S->>K: DEL ff:flag:v2:new-checkout
    S-->>C: 200 with the updated flag
    Note over S,K: The next evaluation misses and rebuilds the snapshot from Postgres
```

- Every write adds its audit event in the same transaction, before the `COMMIT`, so the change and its event are committed or rolled back together. A rejected write (409 or 404) leaves no event, and if the audit `INSERT` fails, the change is rolled back and the request returns 500.
- Every write (create, update, delete, override set or removed) commits first and deletes the flag's snapshot second. Deleting before the commit would let a concurrent read re-cache the old row.
- One rarer race remains: a read that loaded the old row before the commit can write it to the cache just after the delete. The TTL (60s by default) caps how long that stale entry can live. The same TTL covers a failed `DEL` during a cache outage.
- Deleting a flag cascades to its overrides in Postgres (`ON DELETE CASCADE`) and removes its snapshot, so re-creating a flag with the same key starts clean. Its audit events stay: they reference the flag by key, not by a foreign key, so a re-created flag's history continues the old one.
