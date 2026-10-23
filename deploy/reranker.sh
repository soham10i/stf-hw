#!/usr/bin/env bash
# Deploy the copilot's reranker to Cloud Run: text-embeddings-inference serving
# BAAI/bge-reranker-v2-m3 on CPU, scale-to-zero (docs/GCP_RERANKER.md).
#
# Usage: ./deploy/reranker.sh [PROJECT_ID]   (defaults to gcloud's current project)
# Needs: gcloud logged in, run.googleapis.com enabled (the stf-live deploy already did).
# After it prints the service URL, set STF_RERANKER_URL=<url> on the stf-live service
# (Cloud Run console -> stf-live -> Edit -> Add variable) and the copilot reranks from
# the next request - retrieval works without it, so a wrong URL degrades, never breaks.
set -euo pipefail

PROJECT="${1:-$(gcloud config get-value project)}"
REGION="europe-west1"          # same region as stf-live: egress-free, one less hop
SERVICE="stf-reranker"
MODEL="BAAI/bge-reranker-large"   # v2-m3 OOMs on fp32 CPU (~9GiB); large fits 8Gi with headroom

echo "deploying $SERVICE to $PROJECT ($REGION), model $MODEL"
gcloud run deploy "$SERVICE" \
  --project "$PROJECT" \
  --region "$REGION" \
  --image ghcr.io/huggingface/text-embeddings-inference:cpu-latest \
  --args="--model-id,$MODEL" \
  --memory 8Gi --cpu 2 \
  --concurrency 4 \
  --min-instances 0 --max-instances 2 \
  --timeout 300 \
  --cpu-boost \
  --startup-probe=tcpSocket.port=8080,initialDelaySeconds=60,periodSeconds=10,timeoutSeconds=5,failureThreshold=30 \
  --allow-unauthenticated \
  --quiet

URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')"
echo
echo "reranker up: $URL"
echo "smoke test:  curl -s -X POST $URL/rerank -H 'content-type: application/json' \\"
echo "               -d '{\"query\":\"oven\",\"texts\":[\"the oven bakes\",\"the crane lifts\"]}'"
echo
echo "next step:   set STF_RERANKER_URL=$URL on the stf-live service, then verify:"
echo "               STF_RERANKER_URL=$URL make eval-retrieval"
