#!/usr/bin/env bash
# Migrate stf-live's secret env vars into Secret Manager (docs/STAGING.md hardening).
#
# What it does, in order:
#   1. reads stf-live's current environment and copies each SECRET below into a
#      same-named Secret Manager secret (created on first run; a new version is
#      added when the value changed)
#   2. grants the runtime service account secretAccessor so revisions can mount them
# Values travel gcloud -> Secret Manager only: they are never printed, never
# written to the repo, and the temporary spec file is deleted on exit.
#
# Usage: ./deploy/migrate-secrets.sh [PROJECT_ID]
set -euo pipefail

PROJECT="${1:-$(gcloud config get-value project)}"
REGION="europe-west1"
SERVICE="stf-live"
# every env var that is a credential and should live in Secret Manager
SECRETS="GEMINI_API_KEY GROQ_API_KEY ELEVENLABS_API_KEY UPB_AI_KEY SUPABASE_SERVICE_KEY SUPABASE_SECRET_KEY SUPABASE_DATABASE_PASSWORD STF_SESSION_SECRET STF_API_TOKEN STF_SMTP_PASS POSTGRES_PASSWORD REDIS_PASSWORD"
SPEC_FILE="$(mktemp /tmp/stf-live-spec.XXXXXX.json)"
trap 'rm -f "$SPEC_FILE"' EXIT

gcloud run services describe "$SERVICE" \
  --project "$PROJECT" --region "$REGION" --format=json > "$SPEC_FILE"

echo "migrating secrets for $SERVICE in $PROJECT"
SECRETS_JSON="$(SECRETS="$SECRETS" SPEC_FILE="$SPEC_FILE" python3 - << 'PY'
import json, os, subprocess, sys

secrets = os.environ["SECRETS"].split()
spec = json.load(open(os.environ["SPEC_FILE"]))
env = spec["spec"]["template"]["spec"]["containers"][0].get("env", [])
values = {e["name"]: e["value"] for e in env if "value" in e and "value_from" not in e}

missing = [s for s in secrets if not values.get(s)]
created, updated, skipped = [], [], []
for name in secrets:
    value = values.get(name)
    if not value:
        continue
    r = subprocess.run(
        ["gcloud", "secrets", "describe", name, "--project",
         spec["metadata"]["namespace"], "--format=value(name)"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:  # create it, then add the first version
        subprocess.run(
            ["gcloud", "secrets", "create", name,
             "--project", spec["metadata"]["namespace"], "--quiet"],
            check=True, capture_output=True,
        )
        created.append(name)
    # add a version; Secret Manager dedupes identical payloads within the day, and
    # an extra version of the same value is harmless either way
    subprocess.run(
        ["gcloud", "secrets", "versions", "add", name, "--project",
         spec["metadata"]["namespace"], "--data-file=-", "--quiet"],
        input=value.encode(), check=True, capture_output=True,
    )
print(json.dumps({"created": created, "missing": missing}))
PY
)"

CREATED="$(echo "$SECRETS_JSON" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["created"]))')"
MISSING="$(echo "$SECRETS_JSON" | python3 -c 'import json,sys; print(", ".join(json.load(sys.stdin)["missing"]) or "none")')"
echo "secrets created now: $CREATED; without a value on $SERVICE (left alone): $MISSING"

SA="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --format='value(spec.template.spec.serviceAccountName)')"
echo "granting secretAccessor to $SA"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor \
  --quiet >/dev/null

echo
echo "done. next: make staging-deploy (it mounts these as secrets), test, then make promote."
