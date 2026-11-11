# Guarded action: the plan for loop 5

The copilot can read the twin, the documents and the web; it cannot change anything. This plan
adds the one loop that lets it act: the model **proposes** a typed action, a deterministic
precheck tests it, the graph **pauses** until an operator approves the exact payload on a card,
the server **re-checks** fresh state, executes **at most once**, and **observes** the result.
A restart while an approval is pending loses nothing; a replayed or doubled approval does
nothing twice.

Numbering: this is phase 5 in [agent-graph.md](../reference/architecture/agent-graph.md) (loop 5) and Phase 2 in
[the feasibility report](agentic-feasibility-report.md) section 10. Status: **steps 1
and 2 built** (section 9), steps 3-7 open. Decided: named operator keys, actions off on public
`stf-live`, 5-minute proposals.

## 1. Starting point

What exists: five write tools in `services/api/tools.py` (`order_submit`, `order_cancel`,
`alarm_ack`, `recipe_adjust`, `twin_navigate`), an `ActionGuard` in `services/api/actuation.py`
(preconditions, HMAC-signed audit records, e-stop latch), and the Phase 0 freeze: the tools are
neither declared to models nor callable unless `STF_AGENT_ACTUATION=1`
(`tests/test_agent_actuation_freeze.py`).

What reading the code turned up, each of which the plan fixes or works around:

| # | Finding | Where | Consequence |
|---|---|---|---|
| F1 | The audit trail is a Python list; the HMAC secret falls back to a constant in the source | `ActionGuard.__init__` | lost on every restart; anyone with the repo can forge a signature |
| F2 | "Post-execution verification" is always true: `runtime.submit` appends to `_history` before the check reads it | `ActionGuard.execute_order` | no real postcondition exists |
| F3 | The e-stop latch, the recipe and acknowledged alarms live only in the guard; the runtime never reads the recipe, and an acknowledged alarm changes nothing the plant uses | `ActionGuard` | `recipe_adjust` and `alarm_ack` have no observable effect, so no postcondition can be checked |
| F4 | The actor is `ctx.client` (a guest id or `local`) or the literal `"operator"` | tools.py write tools, `POST /command` | no identity, no role, nothing to bind an approval to |
| F5 | `CommandRequest` accepts A1..C4; the guard and the rack accept A1..C3 | `app.py`, `actuation.py` | C4 passes the schema and fails later |
| F6 | `order_cancel` without an id cancels the newest pending order | `SimRuntime.cancel` | a model-filled proposal could cancel an order nobody named |
| F7 | `compute_state_hash` includes the carrier position, which changes on every move | `ActionGuard.compute_state_hash` | useless for "state unchanged since the proposal" |
| F8 | A repeated question is answered from the cache in `prepare` | `agent.prepare` | a cached reply would replay an old proposal card |
| F9 | One `SimRuntime` serves every visitor | `app.runtime` | an approval changes the twin everyone sees, so guests must never approve |
| F10 | Supabase is reached only through PostgREST; there is no Postgres driver in the image | `guests.py`, `visits.py` | the checkpointer brings the first direct connection |

## 2. Decisions

| Question | Choice | Why |
|---|---|---|
| Where the pause lives | A separate **`actuation` graph**, compiled with a checkpointer; the question graph stays as it is, uncheckpointed | the question's working memory (`Question`: the HTTP request, the stream's emit hook) cannot be serialized, and only an action has to outlive a request |
| Which actions | `order_submit` and `order_cancel` only | they change the runtime and have a postcondition that can be observed. `alarm_ack` and `recipe_adjust` stay frozen until the runtime reads them (F3). `twin_navigate` changes no state, so it becomes a read tool that returns a link |
| Checkpointer | `langgraph-checkpoint-postgres` 3.2.0 (requires `langgraph-checkpoint>=4.3,<5`, which matches the pinned 4.3.0) with `psycopg` 3 and `psycopg-pool`, over Supabase's **session pooler** (IPv4, port 5432; Cloud Run has no IPv6 egress to the direct host) | the official saver; session mode keeps prepared statements working |
| Local and tests | `langgraph-checkpoint-sqlite` on a file (restart tests), `InMemorySaver` for unit tests; SQLite refused on Cloud Run | no Docker needed for most tests, and production never keeps approvals on an ephemeral disk |
| Schema | everything in a private schema **`agent`**, never `public` | `saver.setup()` creates its tables without row-level security; in `public`, PostgREST would serve checkpoints to anyone holding the anon key |
| Ledger | our own tables (proposals, executions, audit) beside the checkpoints, through the same pool, with conditional updates | the race guard (exactly one approval wins) needs a real `UPDATE ... WHERE status = 'pending' RETURNING`, which PostgREST makes awkward |
| Who approves | **Named operator keys** (`STF_OPERATORS`), exchanged for a short-lived signed HttpOnly cookie; roles `viewer` and `operator`; guests never approve | the smallest real identity that fits a portfolio twin; Supabase Auth can replace the key exchange later without touching the graph |
| Binding | approval carries the SHA-256 of the canonical payload; the server compares it with the stored proposal and accepts only an unexpired, pending proposal, from an operator | "approve" means approving exactly what the card showed |
| Freshness | the precheck runs again on fresh state after approval, on a **precondition fingerprint** (e-stop, queue length, slot validity, target order's state), not the full state hash | F7: the full hash changes on every move |
| Execution | at most once: an `executions` row is inserted **before** the side effect; a re-run that finds it goes to reconcile, never to a second submit | a crash between the side effect and the checkpoint write must not cause a second order |
| Timeout | the result is `unknown`, the card says so, and an operator reconciles; nothing retries | an industrial agent never retries an actuation by itself |
| Switch | `STF_AGENT_ACTUATION = off` (default) `| propose`; the legacy direct path (`1`) is removed | there is one way to change state from the copilot, and it goes through approval |
| Engine | actions need LangGraph; with `STF_AGENT=linear` the propose path answers "actions unavailable" | `interrupt()` and the checkpointer are LangGraph's; a second implementation is not worth it |
| Deployments | public `stf-live`: off. Private `stf-staging`: `propose`, with operator keys | F9 |

## 3. The actuation graph

```
 propose ──▶ precheck ──refused──────────────────────────────────────────▶ report ──▶ END
                │ ok                                                         ▲
                ▼                                                            │
            approval  ── interrupt(): the graph stops, its checkpoint saved  │
                │  ├─ rejected ─────────────────────────────────────────────┤
                │  └─ expired ──────────────────────────────────────────────┤
                ▼ approved                                                   │
           revalidate ──refused (state changed) ────────────────────────────┤
                │ ok                                                         │
                ▼                                                            │
             execute ──ledger row already there──▶ reconcile ───────────────┤
                │                                     ▲                      │
                ▼                                     │                      │
             observe ──timeout────────────────────────┘                      │
                │ postcondition holds                                        │
                └────────────────────────────────────────────────────────────┘
```

| Node | Does | Side effect | On re-run (resume or crash) |
|---|---|---|---|
| `propose` | validates the typed proposal, computes `payload_hash`, writes the proposal row (`proposed`) | one insert (idempotent on the proposal id) | no-op |
| `precheck` | runs the named rules (section 4) on the live runtime; records each rule's verdict | proposal row: `pending` or `refused` | same answer on the same state |
| `approval` | `interrupt({proposal, hash, expires_at})` **and nothing else** | none | LangGraph re-runs a node from its start on resume, so nothing may come before `interrupt()` |
| `revalidate` | the precheck again, on fresh state, plus expiry | proposal row: `approved` or `refused` | same |
| `execute` | inserts the `executions` row (`started`), then calls the guard's `execute_order` / `execute_order_cancel` | the only change to the runtime | the row exists, so it goes to `reconcile` and never submits again |
| `observe` | polls the runtime until the postcondition holds or `STF_ACTION_OBSERVE_S` (default 5 s) passes | executions row: `done` | polling has no side effect |
| `reconcile` | compares the ledger with the runtime: the order exists with this payload means `done`, otherwise `unknown` | executions row; audit record | has no side effect on the runtime |
| `report` | final status on the proposal row, one signed audit record | audit insert | idempotent on (proposal, status) |

Postconditions: **submit**, an order with the expected op and slot appears in the runtime's
pending or active orders with an id the ledger did not know before; **cancel**, the named order
is no longer pending and its history entry says cancelled.

State (all JSON, nothing request-bound): `proposal`, `payload_hash`, `precheck`
(`[{rule, ok, why}]`), `decision` (`{verdict, actor, role, at}`), `execution` (`{order_id,
audit_id}`), `status`. Status runs `proposed -> pending -> approved -> executing -> done`, or ends
in `refused`, `rejected`, `expired` or `unknown`.

One thread per proposal, `thread_id = "act-<proposal uuid>"`. The graph is invoked with
`durability="sync"`, so each step's checkpoint is written before the next step starts.

How a proposal is born: in `propose` mode a write tool no longer executes; it validates its
arguments into an `ActionProposal` and returns it on the tool `Result` (new field `proposal`),
with the text "prepared, awaiting an operator's approval; nothing has changed". The `respond`
node, which is async and runs once per question, starts the actuation thread (propose ->
precheck -> pause) and puts the proposal's id, status and precheck in the reply. Only the first
write call in a question becomes a proposal; any further one is refused as "one action per
approval". A reply that carries a proposal is never cached (F8).

## 4. Typed proposal, precheck rules and exact-payload binding

```python
SlotId = Annotated[str, StringConstraints(pattern=r"^[A-C][1-3]$")]     # F5: one range

class OrderSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    op: Literal["retrieve", "store", "home", "cycle"]
    slot: SlotId | None = None

class OrderCancel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    order_id: int                                                        # F6: required

class ActionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    v: Literal[1] = 1
    id: UUID
    kind: Literal["order_submit", "order_cancel"]
    params: OrderSubmit | OrderCancel
    reason: str = Field(max_length=300)        # the model's words, shown as such
    evidence: list[str] = Field(max_length=8)  # the tool facts it relied on
    guest: str                                 # salted hash, never the raw guest id
    created_at: float
    expires_at: float                          # created_at + STF_ACTION_TTL_S (default 300)
```

`payload_hash = sha256(canonical)`, where `canonical` is the JSON of `{v, id, kind, params,
expires_at}` with sorted keys, no spaces and normalized values (slot upper case, op lower case).
The proposal id is inside the hash, so two identical orders are two different approvals.

**Precheck as named rules** (built: `actuation.RULES`). `validate_preconditions` is now a list
of small functions, each with one name and one refusal; `ActionGuard.precheck` returns every
applicable rule's verdict for the card:

| Rule | Refuses when |
|---|---|
| `actor_present` | no actor |
| `estop_clear` | the e-stop latch is set (every action but its reset) |
| `op_known` | the op is not one of the four |
| `slot_required` | retrieve, store or cycle without a slot |
| `slot_in_rack` | the slot is not A1..C3, or not in `layout.main_rack` |
| `queue_room` | pending orders >= `MAX_PENDING_ORDERS` |
| `cancel_target_named` | a cancel names no order (F6) |
| `cancel_not_active` | the order to cancel is in production |
| `cancel_target_pending` | the order to cancel is not waiting in the queue |
| `alarm_code_valid`, `bake_temp_envelope`, `conveyor_speed_envelope`, `bake_time_envelope`, `page_known` | the frozen actions' bounds, kept as rules so they are tested the same way |

`not_expired` and the authenticated actor at approval belong to `decide()` (step 3): they test
the proposal and the session, not the plant.

**The decision endpoint** checks, in this order, failing closed at the first miss:

1. operator cookie valid, unexpired, role `operator`, else **403**
2. proposal exists, else **404**
3. not expired (server clock), else **410**, and the thread ends as `expired`
4. `payload_hash` in the body equals the stored one (`hmac.compare_digest`), else **409**
5. `UPDATE agent.action_proposals SET status='approved', decided_by=..., decided_at=now()
   WHERE id=$1 AND status='pending' RETURNING id`; no row returned means another decision won:
   the same verdict gets **200** with the recorded outcome and no resume, a different one **409**
6. resume the thread: `graph.ainvoke(Command(resume=decision), {"configurable": {"thread_id"}})`

The actor always comes from the cookie, never from the body. A reject goes through the same
steps with `status='rejected'`.

## 5. The approval card

`ActionCard` in `web/src/dashboard/copilot/Message.tsx`, drawn when a turn carries `proposal`:

- **What**: "Retrieve from slot B2" (one line from the canonical payload, not the model's
  words), then the model's reason and its evidence, labelled as the copilot's.
- **Precheck**: each rule with a tick or its refusal; a refused proposal shows no buttons.
- **Binding**: the first 8 characters of the payload hash, the expiry as a countdown
  (`aria-live="polite"`), "nothing has changed yet".
- **Buttons**: Approve and Reject, only for an operator session. A guest sees "Needs an
  operator's approval" and an "Operator sign-in" link (a small dialog posting the key to
  `POST /operator/session`; the key is never kept in the page).
- **After a decision**: approved, executing, done (with the order id and audit id), or
  refused, rejected, expired or unknown, from `GET /actions/{id}`, polled once a second until a
  final status. A reload rebuilds the card from the session turn's proposal id.
- The card is the confirmation; there is no second "are you sure" dialog.

API additions (`copilot/api.ts`): `Proposal` on `Turn` and `Reply`; `action(id)`,
`decide(id, verdict, hash)`, `operatorSignIn(key)`, `operatorSignOut()`.

The answer must not claim the action happened. `verify` gains one rule: a reply for a question
with a pending proposal that says done, queued or cancelled is sent back once, like an unbacked
number.

## 6. Storage, retention and privacy

Migration `supabase/migrations/20261028120000_stf_actions.sql`:

- `create schema agent; revoke all on schema agent from anon, authenticated;`
- `agent.action_proposals`: `id uuid pk`, `thread_id text unique`, `guest text`, `kind`,
  `params jsonb`, `payload_hash text`, `reason`, `evidence jsonb`, `precheck jsonb`,
  `status text check (...)`, `created_at`, `expires_at`, `decided_by`, `decided_at`, `note`
- `agent.action_executions`: `proposal_id uuid pk references action_proposals`, `state text
  check (state in ('started','done','unknown'))`, `order_id int`, `result jsonb`,
  `started_at`, `finished_at`
- `agent.action_audit`: `id bigserial`, `at`, `actor`, `action`, `params jsonb`, `pre`, `post`,
  `status`, `reason`, `prev_sig`, `sig`. Append-only: a trigger refuses `UPDATE` and allows
  `DELETE` only for rows older than `STF_AUDIT_DAYS` (default 365); each record signs the one
  before it (`prev_sig`), so a removed or edited row breaks the chain
- the checkpointer's own tables, created by `AsyncPostgresSaver.setup()` with
  `search_path=agent` in the connection options

Connection: a new secret `SUPABASE_DB_URL`, the session pooler address for eu-west-1, port
5432, `sslmode=require`. Pool `min_size=0, max_size=4` per instance (at `--max-instances 2`,
eight connections at most), `autocommit=True`, `row_factory=dict_row` (what the saver needs),
opened on the first action. If the database is down, proposals answer "actions unavailable" and
every read question still works.

Audit secret (F1): `STF_AUDIT_SECRET` is required when `K_SERVICE` or `RENDER` is set; without
it, or with the old constant, the propose path stays off and `/chat/status` says why.

Retention: `DELETE /guest` lists the guest's proposals, deletes their threads
(`saver.adelete_thread`) and their rows; proposals and threads lapse with the guest after
`STF_GUEST_DAYS`. The audit keeps the operator's name and the salted guest hash for
`STF_AUDIT_DAYS`. `web/public/legal/privacy.html` gains a section on operator sign-in and the
audit log before this ships anywhere public.

## 7. Changes by file

| File | Change |
|---|---|
| `services/api/ledger.py` (new, **built**) | the ledger store (`SqliteLedger`, `PgLedger`, `ledger_from_env`): proposals with forward-only conditional transitions, at-most-once executions, the audit chain, retention |
| `services/api/actions.py` (new) | `ActionProposal` and friends, `canonical`/`payload_hash`, the actuation graph, `decide()`, the saver factory |
| `services/api/operators.py` (new) | `STF_OPERATORS` parsing (`name:role:sha256(key)`), key check, signed cookie (`stf_operator`, HttpOnly, SameSite=Strict, Secure, 30 min), `current_operator()` dependency |
| `services/api/actuation.py` | rules list (section 4); audit records go to a sink (memory in tests, `agent.action_audit` in production) with `prev_sig`; mandatory secret; `precondition_fingerprint()`; the always-true verification (F2) removed, its job moved to `observe`; slot range A1..C3 |
| `services/api/tools.py` | write tools return a proposal in `propose` mode; `alarm_ack`/`recipe_adjust` stay frozen; `twin_navigate` becomes a read tool; `Result.proposal`; `actuation_enabled` becomes `actuation_mode()` |
| `services/api/agent.py` | `respond` starts the actuation thread and adds `proposal` to the reply; no cache for a reply with one; `verify` rule for "claims done" |
| `services/api/app.py` | `POST/DELETE /operator/session`, `GET /actions?status=pending` (operators), `GET /actions/{id}` (the guest who asked, or an operator), `POST /actions/{id}/decision`; `DELETE /guest` drops the guest's actions; `CommandRequest` slot range A1..C3 |
| `services/api/chat.py` | `/chat/status` reports the action mode and why it is off |
| `web/src/dashboard/copilot/{api.ts,Message.tsx}`, `Chat.tsx`, `styles/chat.css` | `ActionCard`, types, calls |
| `supabase/migrations/20261028120000_stf_actions.sql` (new) | section 6 |
| `requirements-api.in` / `.txt`, `pyproject.toml` | `langgraph-checkpoint-postgres==3.2.0`, `psycopg[binary]`, `psycopg-pool`; dev: `langgraph-checkpoint-sqlite`; re-locked with `uv pip compile ... --generate-hashes` |
| `.github/workflows/ci.yml` | a `postgres:16` service and `STF_TEST_PG_URL`, so the Postgres tests run in CI |
| `deploy/staging.sh`, `promote.sh` | `SUPABASE_DB_URL`, `STF_AUDIT_SECRET`, `STF_OPERATORS` in `SECRET_NAMES` |
| `docs/reference/architecture/agent-graph.md`, `docs/reference/operations/database.md`, `privacy.html` | loop 5 status, the new tables, the privacy section |

## 8. Tests: the gate

New files `tests/test_actions_precheck.py`, `tests/test_actions_flow.py`,
`tests/test_actions_restart.py`, `tests/test_actions_api.py`, `tests/test_operators.py`. Every
flow and restart test runs twice, on the SQLite saver and, when `STF_TEST_PG_URL` is set (CI,
or `docker compose up timescale` locally), on the Postgres saver.

| Test | Setup | Passes when |
|---|---|---|
| **precheck mutants** | for each rule in the list: a payload that only that rule refuses | refused with that rule's name; then, with that one rule removed from the list, the same payload passes, which proves each test pins its own rule |
| round trip | propose `retrieve B2`, approve with the right hash | thread paused at `approval`; after approval one new order with op and slot as proposed; audit chain `pending, approved, executed, done` verifies |
| reject | propose, reject | no order; status `rejected`; thread finished |
| **restart while pending** | process A (a subprocess) proposes, then `os._exit(0)`; process B starts fresh and approves | B resumes the same thread from its checkpoint (history shows `approval` then `revalidate`), executes once |
| **restart after state loss** | as above, but the proposal cancels order #N, and the new process's runtime no longer has it | `revalidate` refuses (`cancel_target_pending`); nothing executes |
| **crash after the side effect** | a hook ends process A inside `execute`, after `submit`, before the checkpoint | process B's resume finds the ledger row, goes to `reconcile`, reports `done` for the order that exists; the runtime holds exactly one such order |
| **replay** | approve, then send the identical approval again | second answer is 200 with the recorded outcome; one order |
| **double click** | 10 approvals at once (`asyncio.gather`) | exactly one resumes the thread; one order |
| changed payload | approve with another proposal's hash, and with one character changed | 409; nothing executed; proposal still pending |
| changed state | fill the queue to `MAX_PENDING_ORDERS` between propose and approve | `revalidate` refuses (`queue_room`) |
| e-stop | latch the e-stop between propose and approve | refused (`estop_clear`) |
| expired | advance the clock past `expires_at` | 410; status `expired`; no order |
| wrong actor | no cookie; a guest cookie; a forged cookie; a `viewer` | 403 each; nothing changes |
| observe timeout | the runtime hides the new order | status `unknown`, never `done`; no second submit |
| guest deletion | `DELETE /guest` with two proposals | rows and checkpoint threads gone; audit rows stay, with the guest only as a hash |
| freeze unchanged | flag `off` | no write tool declared; `tests/test_agent_actuation_freeze.py` green |
| public deployment | `K_SERVICE` set, no `STF_AUDIT_SECRET` | the propose path is off and says why |
| both engines | a question "bake a cookie from B2" on `graph` and on `linear` | graph: a proposal card; linear: "actions unavailable"; no state change on either |
| cache | ask the same action question twice | two proposals, two ids; the second is not a cache hit |

Gate to call the phase done: the whole suite green on both engines; the new tests green on
SQLite and on Postgres in CI; the copilot eval unchanged (the read questions never see the
write tools); and one manual run on staging: propose, deploy a new revision while the proposal
is pending, approve on the phone, see the order on the twin.

## 9. Order of work

| Step | Work | Estimate |
|---|---|---|
| 1 | **done**: precheck as named rules; F2, F5, F6 fixes; mutant tests (`tests/test_actions_precheck.py`) | 0.5-1 day |
| 2 | **done**: migration; ledger store (Postgres and SQLite); audit chain; required secret; intent recorded before each side effect; Postgres in CI (`tests/test_ledger.py`) | 1 day |
| 3 | actuation graph, saver factory, `decide()`, operator sign-in, endpoints | 1.5-2 days |
| 4 | tools in propose mode, `Result.proposal`, `respond` wiring, no cache, `verify` rule | 0.5 day |
| 5 | approval card and API client | 1 day |
| 6 | restart, crash, replay and concurrency tests; Postgres in CI | 1 day |
| 7 | staging rollout; docs and privacy page | 0.5 day |

About six to seven days. Steps 1 and 2 do not depend on each other; step 5 can start once the
endpoint shapes from step 3 are fixed.

## 10. Rollout and rollback

Owner, on staging only: apply the migration; create the `SUPABASE_DB_URL`, `STF_AUDIT_SECRET`
and `STF_OPERATORS` secrets; set `STF_AGENT_ACTUATION=propose`. Public `stf-live` stays `off`.

Rollback is the switch: `STF_AGENT_ACTUATION=off` removes the propose path; pending proposals
expire on their own; the schema and the audit stay.

## 11. Out of scope

Physical hardware; multi-step plans (one proposal per approval); `alarm_ack` and
`recipe_adjust` until the runtime reads them; Supabase Auth and SSO; a two-person rule; the MCP
server; alarm triage (loop 6).

## 12. Open decisions

1. **Operator identity**: named operator keys now (recommended), or Supabase Auth now (more
   work: sign-in UI, JWT verification against `SUPABASE_JWKS_URL`, roles in app metadata).
2. **Public `stf-live`**: actions off (recommended), or proposals shown to guests with no way
   to approve (a demo of the card; it still needs the database and the audit secret).
3. **Proposal lifetime**: 5 minutes by default (`STF_ACTION_TTL_S`).
