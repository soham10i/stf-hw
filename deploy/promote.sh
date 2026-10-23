#!/usr/bin/env bash
# Promote the current tree from staging to the public service (docs/STAGING.md).
# Rebuilds stf-live from the same source that just passed on stf-staging, keeping
# stf-live's existing environment untouched (read at deploy time, never printed,
# never written to the repo). Cloud Run keeps the previous revision, so rollback is:
#   gcloud run services update-traffic stf-live --region europe-west1 \
#       --to-revisions <previous-revision-name>=100
# (revision names: gcloud run revisions list --service stf-live --region europe-west1)
#
# Usage: ./deploy/promote.sh [PROJECT_ID]   (defaults to gcloud's current project)
# Run ./deploy/staging.sh first and test there; this assumes staging passed.
set -euo pipefail

PROJECT="${1:-$(gcloud config get-value project)}"
REGION="europe-west1"
SERVICE="stf-live"
ENV_FILE="$(mktemp /tmp/stf-promote-env.XXXXXX.yaml)"
SPEC_FILE="$(mktemp /tmp/stf-live-spec.XXXXXX.json)"
trap 'rm -f "$ENV_FILE" "$SPEC_FILE"' EXIT

echo "promoting current tree to $SERVICE ($PROJECT, $REGION); environment carried over verbatim"

# Plain env carries over; the Secret Manager names arrive via --set-secrets instead
# (they were plain values before the migration - promote is what removes them).
SECRET_NAMES="GEMINI_API_KEY GROQ_API_KEY ELEVENLABS_API_KEY UPB_AI_KEY SUPABASE_SERVICE_KEY SUPABASE_SECRET_KEY SUPABASE_DATABASE_PASSWORD STF_SMTP_PASS POSTGRES_PASSWORD REDIS_PASSWORD"
gcloud run services describe "$SERVICE" \
  --project "$PROJECT" --region "$REGION" --format=json > "$SPEC_FILE"
SECRET_NAMES="$SECRET_NAMES" python3 - "$SPEC_FILE" "$ENV_FILE" << 'PY'
import json, os, sys
secret_names = set(os.environ["SECRET_NAMES"].split())
spec = json.load(open(sys.argv[1]))
env = spec["spec"]["template"]["spec"]["containers"][0].get("env", [])
out = {}
for e in env:
    if "value" in e and "value_from" not in e and e["name"] not in secret_names:
        out[e["name"]] = e["value"]
with open(sys.argv[2], "w") as f:
    f.write("\n".join(f"{k}: {json.dumps(v)}" for k, v in sorted(out.items())) + "\n")
PY

SET_SECRETS="$(for s in $SECRET_NAMES; do printf '%s=%s:latest,' "$s" "$s"; done)"
SET_SECRETS="${SET_SECRETS%,}"

gcloud run deploy "$SERVICE" \
  --project "$PROJECT" \
  --region "$REGION" \
  --source . \
  --platform managed \
  --allow-unauthenticated \
  --port 10000 \
  --memory 1Gi --cpu 1 \
  --min-instances 0 --max-instances 2 \
  --timeout 300 \
  --env-vars-file "$ENV_FILE" \
  --set-secrets "$SET_SECRETS" \
  --quiet

URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')"
echo
echo "live updated: $URL"
echo "verify: curl $URL/health   (the keep-warm job and uptime monitor cover this URL)"
