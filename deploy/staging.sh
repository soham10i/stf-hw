#!/usr/bin/env bash
# Deploy the private staging mirror of the API: same code, same configuration as
# stf-live, no public traffic. Development and testing happen here (docs/STAGING.md);
# the public URL (stf-live) only ever receives code that passed on staging.
#
# Usage: ./deploy/staging.sh [PROJECT_ID]   (defaults to gcloud's current project)
# Needs: gcloud logged in; run.googleapis.com enabled.
#
# How it is configured: stf-live's environment is read at deploy time and copied
# verbatim (secrets included - they are never written to the repo or printed).
# Staging-only deltas are applied on top: Swagger on (STF_API_DOCS=1) and the
# notify email blanked so staging can never send mail.
#
# Access: the caller's account is the only invoker. Requests carry an identity token:
#   curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
#        https://stf-staging-…-ew.a.run.app/health
set -euo pipefail

PROJECT="${1:-$(gcloud config get-value project)}"
REGION="europe-west1"          # same region as stf-live: egress-free, one less hop
SERVICE="stf-staging"
LIVE="stf-live"
INVOKER="$(gcloud config get-value account)"   # whoever deploys can call it
ENV_FILE="$(mktemp /tmp/stf-staging-env.XXXXXX.yaml)"
SPEC_FILE="$(mktemp /tmp/stf-live-spec.XXXXXX.json)"
trap 'rm -f "$ENV_FILE" "$SPEC_FILE"' EXIT

echo "deploying $SERVICE to $PROJECT ($REGION); invoker: $INVOKER"
echo "copying $LIVE's environment (secrets stay in transit, never on disk in the repo)"

# stf-live's env -> YAML for --env-vars-file, with the two staging deltas applied and
# the Secret Manager names dropped (they arrive via --set-secrets instead).
SECRET_NAMES="GEMINI_API_KEY GROQ_API_KEY ELEVENLABS_API_KEY UPB_AI_KEY SUPABASE_SERVICE_KEY SUPABASE_SECRET_KEY SUPABASE_DATABASE_PASSWORD STF_SMTP_PASS POSTGRES_PASSWORD REDIS_PASSWORD"
gcloud run services describe "$LIVE" \
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
out["STF_API_DOCS"] = "1"     # Swagger at /docs - private service, so this is safe
out["STF_NOTIFY_EMAIL"] = ""  # staging must never send mail
with open(sys.argv[2], "w") as f:
    f.write("\n".join(f"{k}: {json.dumps(v)}" for k, v in sorted(out.items())) + "\n")
PY

# the migrated credentials, mounted as Secret Manager values (docs/STAGING.md)
SET_SECRETS="$(for s in $SECRET_NAMES; do printf '%s=%s:latest,' "$s" "$s"; done)"
SET_SECRETS="${SET_SECRETS%,}"

gcloud run deploy "$SERVICE" \
  --project "$PROJECT" \
  --region "$REGION" \
  --source . \
  --platform managed \
  --no-allow-unauthenticated \
  --port 10000 \
  --memory 1Gi --cpu 1 \
  --min-instances 0 --max-instances 2 \
  --timeout 300 \
  --env-vars-file "$ENV_FILE" \
  --set-secrets "$SET_SECRETS" \
  --quiet

# Private means private: only the deploying account may invoke it.
gcloud run services remove-iam-policy-binding "$SERVICE" \
  --project "$PROJECT" --region "$REGION" \
  --member "allUsers" --role roles/run.invoker --quiet 2>/dev/null || true
gcloud run services add-iam-policy-binding "$SERVICE" \
  --project "$PROJECT" --region "$REGION" \
  --member "user:$INVOKER" --role roles/run.invoker --quiet >/dev/null

URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')"
echo
echo "staging up (private): $URL"
echo "smoke test:  curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" $URL/health"
echo "swagger:     same header, open $URL/docs"
echo
echo "promote when stable: make promote   (rebuilds $LIVE from the same tree - docs/STAGING.md)"
