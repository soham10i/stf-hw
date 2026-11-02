"""STF Digital Twin API Service.

Domain subpackages:
    - core: Simulation runtime, networking, and telemetry
    - industrial: OPC UA/AAS bridges, closed-loop actuation, safety guards
    - agent: AI Copilot graph workflow, tool loop, faithfulness verification
    - rag: BM25/vector search, query rewriting, document grounding
    - providers: LLM model pool, token budgeting, cloud authentication
    - voice: Speech synthesis, transcription, mathematical pronunciation
    - storage: Database persistence, session store, guest lifecycle
    - security: Role-based authorization, SSRF protection, alerts
    - eval: Benchmarking harnesses and automated regression gates
"""

import importlib
import importlib.util
import os
import sys

_DOMAINS = {"core", "industrial", "agent", "rag", "providers", "voice", "storage", "security", "eval"}

_MODULE_ROUTING = {
    # core
    "cycle": "services.api.core.cycle",
    "envcfg": "services.api.core.envcfg",
    "keepalive": "services.api.core.keepalive",
    "live": "services.api.core.live",
    "livehub": "services.api.core.livehub",
    "logging_config": "services.api.core.logging_config",
    "names": "services.api.core.names",
    "runtime": "services.api.core.runtime",
    "tracing": "services.api.core.tracing",
    "wire": "services.api.core.wire",

    # industrial
    "actions": "services.api.industrial.actions",
    "actuation": "services.api.industrial.actuation",
    "industrial_io": "services.api.industrial.industrial_io",
    "ledger": "services.api.industrial.ledger",
    "operators": "services.api.industrial.operators",
    "watchdog": "services.api.industrial.watchdog",

    # agent
    "agent": "services.api.agent",
    "chat": "services.api.agent.chat",
    "depth": "services.api.agent.depth",
    "orchestrate": "services.api.agent.orchestrate",
    "respond": "services.api.agent.respond",
    "toolloop": "services.api.agent.toolloop",
    "tools": "services.api.agent.tools",
    "verify": "services.api.agent.verify",

    # rag
    "crag": "services.api.rag.crag",
    "gemini_search": "services.api.rag.gemini_search",
    "grounded_search": "services.api.rag.grounded_search",
    "grounding": "services.api.rag.grounding",
    "rewrite": "services.api.rag.rewrite",
    "scholar": "services.api.rag.scholar",
    "source_policy": "services.api.rag.source_policy",
    "vectors": "services.api.rag.vectors",
    "websearch": "services.api.rag.websearch",

    # providers
    "gcp_auth": "services.api.providers.gcp_auth",
    "gemini_pool": "services.api.providers.gemini_pool",
    "llm_pool": "services.api.providers.llm_pool",
    "model_check": "services.api.providers.model_check",
    "model_cost": "services.api.providers.model_cost",
    "token_budget": "services.api.providers.token_budget",

    # voice
    "fluent_math": "services.api.voice.fluent_math",
    "mathspeak": "services.api.voice.mathspeak",
    "tts": "services.api.voice.tts",
    "voice_check": "services.api.voice.voice_check",

    # storage
    "captures": "services.api.storage.captures",
    "db_check": "services.api.storage.db_check",
    "db_seed": "services.api.storage.db_seed",
    "factory_db": "services.api.storage.factory_db",
    "guests": "services.api.storage.guests",
    "sessions": "services.api.storage.sessions",
    "store": "services.api.storage.store",
    "usage": "services.api.storage.usage",
    "visits": "services.api.storage.visits",

    # security
    "netguard": "services.api.security.netguard",
    "notify": "services.api.security.notify",
    "security": "services.api.security",

    # eval
    "eval_copilot": "services.api.eval.eval_copilot",
    "eval_gate": "services.api.eval.eval_gate",
    "eval_retrieval": "services.api.eval.eval_retrieval",
}

def __getattr__(name):
    if name in _DOMAINS:
        mod = importlib.import_module(f"services.api.{name}")
        return mod
    if name in _MODULE_ROUTING:
        mod = importlib.import_module(_MODULE_ROUTING[name])
        sys.modules[f"services.api.{name}"] = mod
        return mod
    raise AttributeError(f"module 'services.api' has no attribute '{name}'")

class _CompatibilityFinder:
    _busy = False

    @classmethod
    def find_spec(cls, fullname, path=None, target=None):
        if cls._busy or not fullname.startswith("services.api."):
            return None
        parts = fullname.split(".")
        if len(parts) == 3:
            sub = parts[2]
            this_dir = os.path.dirname(__file__)
            if os.path.exists(os.path.join(this_dir, f"{sub}.py")):
                return None
            if sub in _MODULE_ROUTING:
                cls._busy = True
                try:
                    return importlib.util.find_spec(_MODULE_ROUTING[sub])
                finally:
                    cls._busy = False
        return None

if not any(isinstance(finder, type) and finder.__name__ == "_CompatibilityFinder" for finder in sys.meta_path):
    sys.meta_path.insert(0, _CompatibilityFinder)

__all__ = list(_DOMAINS) + list(_MODULE_ROUTING.keys())
