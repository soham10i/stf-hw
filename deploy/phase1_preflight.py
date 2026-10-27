#!/usr/bin/env python3
"""Read-only Phase 1 staging checks. No secrets or environment values are printed.

Run: python deploy/phase1_preflight.py --project smart-tabletop-factory-512013
Add --live-chat only when a small paid Vertex question is intentionally allowed.
Credits, expiry, FX and billing-budget alerts remain manual owner checks.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import urllib.request


def run(args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if p.returncode:
        detail = p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "gcloud failed"
        raise RuntimeError(detail)
    return p.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    ap.add_argument("--service", default="stf-staging")
    ap.add_argument("--region", default="europe-west1")
    ap.add_argument("--live-chat", action="store_true")
    ap.add_argument("--output")
    a = ap.parse_args()
    checks = []

    def check(name, ok, detail, manual=False):
        checks.append({"check": name, "status": "manual" if manual else "pass" if ok else "blocked",
                       "detail": detail})

    if not a.project:
        check("project", False, "pass --project or set GOOGLE_CLOUD_PROJECT")
    if not shutil.which("gcloud"):
        check("gcloud", False, "install and authenticate Google Cloud CLI")
        report = {"checks": checks}
        print(json.dumps(report, indent=1))
        raise SystemExit(1)

    spec = None
    runtime_sa = None
    try:
        account = run(["gcloud", "auth", "list", "--filter=status:ACTIVE",
                       "--format=value(account)"])
        check("authenticated account", bool(account), account or "run gcloud auth login")
        enabled = run(["gcloud", "services", "list", "--enabled", "--project", a.project,
                       "--format=value(config.name)"]).splitlines()
        required_apis = (
            "aiplatform.googleapis.com",
            "run.googleapis.com",
            "secretmanager.googleapis.com",
        )
        for api in required_apis:
            check(f"API {api}", api in enabled, "enabled" if api in enabled else "not enabled")
        raw = run(["gcloud", "run", "services", "describe", a.service,
                   "--project", a.project, "--region", a.region, "--format=json"])
        spec = json.loads(raw)
        template = spec["spec"]["template"]
        runtime_sa = (template.get("spec", {}).get("serviceAccountName")
                      or spec["spec"]["template"]["metadata"].get("annotations", {}).get(
                          "run.googleapis.com/service-account"))
        check(
            "private staging service",
            True,
            f"{a.service} in {a.region}; runtime identity described",
        )
        env = template["spec"]["containers"][0].get("env", [])
        names = {e["name"]: e for e in env}
        check("Vertex configured", bool(names.get("GEMINI_VERTEX_PROJECT", {}).get("value")),
              "project variable present" if "GEMINI_VERTEX_PROJECT" in names else "not configured")
        check("session signing secret", "STF_SESSION_SECRET" in names,
              "configured" if "STF_SESSION_SECRET" in names else "create/mount STF_SESSION_SECRET")
        check("agent actuation frozen", names.get("STF_AGENT_ACTUATION", {}).get("value", "0")
              .lower() not in ("1", "true", "yes"), "STF_AGENT_ACTUATION must be 0")
        check("metadata-only traces", names.get("STF_TRACE_CONTENT", {}).get("value", "0")
              .lower() not in ("1", "true", "yes"), "STF_TRACE_CONTENT must be 0")
        check("daily spend circuit", bool(names.get("GEMINI_CLOUD_USD_PER_DAY", {}).get("value")),
              "configured" if "GEMINI_CLOUD_USD_PER_DAY" in names else "set a daily USD limit")
        total = all(k in names for k in ("GEMINI_CLOUD_USD_TOTAL", "GEMINI_CLOUD_BUDGET_START"))
        check("pilot spend circuit", total, "fixed-window total and start configured" if total
              else "set GEMINI_CLOUD_USD_TOTAL and GEMINI_CLOUD_BUDGET_START")
    except (RuntimeError, KeyError, ValueError) as e:
        check("staging inspection", False, str(e))

    if runtime_sa:
        try:
            policy = json.loads(run(["gcloud", "projects", "get-iam-policy", a.project,
                                     "--format=json"]))
            members = {m for b in policy.get("bindings", [])
                       if b.get("role") == "roles/aiplatform.user" for m in b.get("members", [])}
            member = f"serviceAccount:{runtime_sa}"
            check("runtime Vertex IAM", member in members,
                  f"{runtime_sa} has roles/aiplatform.user" if member in members
                  else f"grant {runtime_sa} roles/aiplatform.user")
        except (RuntimeError, ValueError) as e:
            check("runtime Vertex IAM", False, f"policy unreadable; owner must verify: {e}")
    else:
        check("runtime identity", False, "could not determine the staging service account")

    check("credit balance, expiry and billing currency", False,
          "verify in Billing → Credits; €250/60 days is not an API-verified budget", manual=True)
    check("billing alerts at 50/80/90/100%", False,
          "create/verify in Billing → Budgets & alerts; alerts alone do not cap spend", manual=True)

    if a.live_chat and spec:
        try:
            url = spec["status"]["url"]
            token = run(["gcloud", "auth", "print-identity-token"])
            body = json.dumps({
                "question": "which part needs service first?",
                "provider": "gemini",
            }).encode()
            req = urllib.request.Request(f"{url}/chat", data=body, method="POST", headers={
                "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as response:
                answer = json.loads(response.read())
            model = answer.get("model", "")
            vertex = any(str(m).startswith("vertex:")
                         for m in (answer.get("usage") or {}).get("models", {}))
            check("paid Vertex end-to-end", vertex,
                  f"response model={model}; priced model usage observed={vertex}")
        except Exception as e:
            check("paid Vertex end-to-end", False, f"live request failed: {type(e).__name__}: {e}")

    report = {"project": a.project, "service": a.service,
              "passed": all(c["status"] in ("pass", "manual") for c in checks), "checks": checks}
    text = json.dumps(report, indent=1) + "\n"
    if a.output:
        with open(a.output, "w", encoding="utf-8") as f:
            f.write(text)
    print(text, end="")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
