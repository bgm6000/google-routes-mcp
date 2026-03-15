#!/bin/bash
# Deploy google-routes MCP server to Cloud Run
# Usage: ./deploy.sh <gcp-project-id> <auth-token>
#
# Prerequisites:
#   brew install google-cloud-sdk
#   gcloud auth login
#   gcloud services enable run.googleapis.com --project=$PROJECT

set -euo pipefail

PROJECT=${1:?"Usage: ./deploy.sh <gcp-project-id> <auth-token>"}
AUTH_TOKEN=${2:?"Usage: ./deploy.sh <gcp-project-id> <auth-token>"}
SERVICE=google-routes-mcp
REGION=us-central1
IMAGE=gcr.io/$PROJECT/$SERVICE

echo "Building image..."
gcloud builds submit \
  --tag "$IMAGE" \
  --project "$PROJECT" \
  .

echo "Deploying to Cloud Run..."
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_ROUTES_API_KEY=AIzaSyCuMBaAPdm7usEFd0tx3qri9uvsp1nTC0w,MCP_AUTH_TOKEN=$AUTH_TOKEN" \
  --project "$PROJECT"

URL=$(gcloud run services describe "$SERVICE" \
  --region "$REGION" \
  --project "$PROJECT" \
  --format "value(status.url)")

echo ""
echo "Deployed: $URL"
echo ""
echo "Add this to claude_desktop_config.json:"
echo '{
  "mcpServers": {
    "google-routes": {
      "url": "'"$URL"'/sse",
      "headers": {
        "Authorization": "Bearer '"$AUTH_TOKEN"'"
      }
    }
  }
}'
