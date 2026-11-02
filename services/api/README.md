# STF Digital Twin - API Architecture & Domain Directory

This directory houses the FastAPI backend service for the **fischertechnik Fabrik Simulation 24V (Model 536634) Digital Twin**. It bridges physical industrial automation, real-time 3D simulation, and an autonomous AI copilot with formal safety verification.

---

## Architecture Overview

To provide a clear, professional directory structure without breaking existing imports, the API is organized into domain-specific subpackages under `services/api/`:

```
services/api/
├── app.py                     # Central FastAPI application & route registration
├── README.md                  # This architecture directory & reference guide
├── __init__.py                # Package root with dynamic backwards-compatibility resolver
│
├── core/                      # Simulation runtime, wire serialization & telemetry
│   ├── runtime.py             # Authoritative asyncio simulation kernel
│   ├── livehub.py             # WebSocket hub (/twin/live, /ws) for 3D state sync
│   ├── live.py                # Snapshot bridge for copilot live_state tool
│   ├── wire.py                # Binary & JSON frame serialization
│   ├── envcfg.py              # Centralized environment variable parsing
│   ├── logging_config.py      # Structured JSON logging
│   ├── tracing.py             # OpenTelemetry spans & instrumentation
│   ├── names.py               # Component and generator naming utilities
│   ├── cycle.py               # Material flow cycle & order definitions
│   └── keepalive.py           # Persistent HTTP connection pooling
│
├── industrial/                # Industrial OT, protocol bridges & hardware safety
│   ├── industrial_io.py       # OPC UA (IEC 62541) & AAS (IEC 63278) bridge
│   ├── actuation.py           # Closed-loop engine & physical safety invariant guards
│   ├── actions.py             # Guarded action proposal state machine
│   ├── ledger.py              # Tamper-evident ledger with HMAC-SHA256 audit chain
│   ├── operators.py           # Operator authentication & RBAC
│   └── watchdog.py            # Telemetry watchdog & anomaly detector
│
├── agent/                     # AI Copilot reasoning & execution graph
│   ├── graph.py               # LangGraph-style workflow graph & state transitions (aliased as agent)
│   ├── chat.py                # High-level chat orchestrator & SSE streaming
│   ├── orchestrate.py         # Intent classification & question complexity routing
│   ├── toolloop.py            # Generic multi-provider tool execution & retry loop
│   ├── tools.py               # Domain tools querying live twin state & telemetry
│   ├── verify.py              # Faithfulness validator (checks numbers against twin)
│   ├── respond.py             # Structured response templating
│   └── depth.py               # Dynamic compute depth & token budget allocation
│
├── rag/                       # Search, retrieval & knowledge grounding
│   ├── grounding.py           # BM25 inverted index over twin documentation
│   ├── vectors.py             # Dense semantic vector search (MiniLM / Cloud)
│   ├── rewrite.py             # Query reformulation & HyDE expansion
│   ├── crag.py                # Corrective Retrieval-Augmented Generation evaluator
│   ├── websearch.py           # Outbound search engine integration (DuckDuckGo, Groq)
│   ├── grounded_search.py     # Grounded Google Search tool adapter
│   ├── scholar.py             # Academic literature retrieval via OpenAlex
│   └── source_policy.py       # Domain whitelisting & citation scoring
│
├── providers/                 # Model provider adapters & cost management
│   ├── llm_pool.py            # Resilient model failover pool with RetryInfo backoff
│   ├── gemini_pool.py         # Gemini-specific connection pool
│   ├── token_budget.py        # Token accounting & question spend caps
│   ├── model_cost.py          # Pricing catalog & global circuit breakers
│   ├── model_check.py         # Model availability & latency probe
│   └── gcp_auth.py            # Cloud OAuth2 access token manager
│
├── voice/                     # Audio, speech & mathematical linguistics
│   ├── tts.py                 # TTS/STT engine (ElevenLabs, Whisper, cloud models)
│   ├── mathspeak.py           # LaTeX to natural phonetic speech converter
│   ├── fluent_math.py         # Equation spoken-reading parser
│   └── voice_check.py         # Voice diagnostics & Word Error Rate (WER) probe
│
├── storage/                   # Databases, sessions & guest tracking
│   ├── factory_db.py          # Relational database client (Supabase / SQLite)
│   ├── db_check.py            # Database health & schema verification
│   ├── db_seed.py             # Database initialization & sample seeding
│   ├── store.py               # Lightweight JSON document store
│   ├── sessions.py            # Multi-turn chat session persistence
│   ├── guests.py              # Anonymous guest lifecycle & signed cookies
│   ├── visits.py              # Consent-gated usage analytics
│   ├── captures.py            # Visual quality inspection photos
│   └── usage.py               # Instance rate limits & quotas
│
├── security/                  # Access control & network boundaries
│   ├── rules.py               # Role-Based Access Control (RBAC) & token validation (aliased as security)
│   ├── netguard.py            # SSRF protection on outbound requests
│   └── notify.py              # Alert notification dispatcher (webhooks/email)
│
└── eval/                      # Evaluation suites & quality gates
    ├── eval_copilot.py        # Automated benchmarking against golden question sets
    ├── eval_gate.py           # CI regression gate (accuracy, latency, cost)
    └── eval_retrieval.py      # RAG precision & recall benchmark
```

---

## Import Compatibility

All modules can be imported using either the structured domain subpackages or the top-level backwards-compatible exports:

```python
# Structured Domain Imports:
from services.api.industrial import actuation as ACT
from services.api.agent import graph as A, tools as T
from services.api.rag import vectors as V, grounding as G
from services.api.providers import llm_pool as LP

# Top-Level Direct Imports (Backwards Compatible):
from services.api import actuation as ACT
from services.api import agent as A
from services.api import tools as T
```

CLI entry points (e.g., `python -m services.api.db_check` or `python -m services.api.model_check`) remain fully functional via forwarding shims and meta-path compatibility finders.
