#!/usr/bin/env bash
# Explicit, owner-run Phase 1 activation on PRIVATE staging only. This changes IAM and Cloud Run.
# Review deploy/phase1_preflight.py and docs/history/2026-10-phase-0-1-implementation.md first.
set -euo pipefail

if [[ "${CONFIRM_PHASE1:-}" != "1" ]]; then
  echo "refusing cloud changes: set CONFIRM_PHASE1=1 after reviewing the staging plan" >&2
  exit 2
fi
: "${PILOT_USD:?set the agreed fixed-window model budget in USD}"
: "${BUDGET_START:?set the pilot start as YYYY-MM-DD}"
DAILY_USD="${DAILY_USD:-5}"
PROJECT="${1:-$(gcloud config get-value project)}"
REGION="europe-west1"
SERVICE="stf-staging"

# Never enable a paid lane before durable session signing and frozen agent writes are configured.
python3 - "$PROJECT" "$REGION" "$SERVICE" <<'PY'
import json, subprocess, sys
project, region, service = sys.argv[1:]
raw = subprocess.check_output([
    "gcloud", "run", "services", "describe", service, "--project", project,
    "--region", region, "--format=json"], text=True)
spec = json.loads(raw)
env = spec["spec"]["template"]["spec"]["containers"][0].get("env", [])
if "STF_SESSION_SECRET" not in {e["name"] for e in env}:
    raise SystemExit("blocked: mount STF_SESSION_SECRET on staging before enabling Vertex")
PY

RUNTIME_SA="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --format='value(spec.template.spec.serviceAccountName)')"
if [[ -z "$RUNTIME_SA" ]]; then
  echo "blocked: staging runtime service account could not be determined" >&2
  exit 1
fi

echo "enabling Vertex API and granting $RUNTIME_SA roles/aiplatform.user on $PROJECT"
gcloud services enable aiplatform.googleapis.com --project "$PROJECT"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$RUNTIME_SA" --role="roles/aiplatform.user" --quiet >/dev/null

# Delimiter @ avoids commas in the model/provider ladders. No credential value appears here.
gcloud run services update "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --update-env-vars "^@^GEMINI_VERTEX_PROJECT=$PROJECT@GEMINI_VERTEX_LOCATION=global@GEMINI_CLOUD_MODELS=gemini-3.8-flash,gemini-3.5-flash@GEMINI_CLOUD_USD_PER_DAY=$DAILY_USD@GEMINI_CLOUD_USD_TOTAL=$PILOT_USD@GEMINI_CLOUD_BUDGET_START=$BUDGET_START@GEMINI_CLOUD_BUDGET_DAYS=60@STF_QUICK_ORDER=gemini,groq,ollama@WEB_SEARCH_ORDER=gemini,groq,ddg@STF_AGENT_ACTUATION=0@STF_TRACE_CONTENT=0@STF_API_TOKEN=" \
  --quiet

echo "staging Vertex configuration updated; public stf-live was not changed"
python3 deploy/phase1_preflight.py --project "$PROJECT" --service "$SERVICE" --region "$REGION"
echo "after owner credit/budget checks, run the same preflight with --live-chat"
