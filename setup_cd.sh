#!/usr/bin/env bash
# -----------------------------------------------------------------------
# setup_cd.sh — One-time setup for continuous deployment via Cloud Build
#
# Prerequisites:
#   1. gcloud CLI installed and authenticated
#   2. GitHub repo connected to Cloud Build
#      (do this once in GCP Console → Cloud Build → Repositories)
#   3. Fill in the variables below before running
#
# Run with:  bash setup_cd.sh
# -----------------------------------------------------------------------

set -euo pipefail

# ── Edit these ──────────────────────────────────────────────────────────
PROJECT_ID="savvy-437819"
REGION="us-central1"
REPO_OWNER="chikondiman"
REPO_NAME="tlc_backend"
CLOUD_SQL_INSTANCE="$PROJECT_ID:$REGION:savvy-db"
# ────────────────────────────────────────────────────────────────────────

echo "▶ Setting project..."
gcloud config set project "$PROJECT_ID"

echo "▶ Enabling required APIs..."
gcloud services enable \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  containerregistry.googleapis.com \
  secretmanager.googleapis.com

echo "▶ Granting Cloud Build the Cloud Run deployer role..."
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
CB_SA="$PROJECT_NUMBER@cloudbuild.gserviceaccount.com"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$CB_SA" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$CB_SA" \
  --role="roles/iam.serviceAccountUser"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$CB_SA" \
  --role="roles/cloudsql.client"

echo "▶ Creating Cloud Build trigger on push to main..."
gcloud builds triggers create github \
  --repo-name="$REPO_NAME" \
  --repo-owner="$REPO_OWNER" \
  --branch-pattern="^main$" \
  --build-config="cloudbuild.yaml" \
  --substitutions="_REGION=$REGION,_CLOUD_SQL_INSTANCE=$CLOUD_SQL_INSTANCE" \
  --name="deploy-on-push-to-main" \
  --description="Auto-deploy tlc-backend to Cloud Run on push to main"

echo ""
echo "✅ Done. Every push to main will now automatically deploy to Cloud Run."
echo ""
echo "Next steps:"
echo "  1. Verify the trigger at: https://console.cloud.google.com/cloud-build/triggers"
echo "  2. Make sure your Cloud Run service has the correct env vars / secrets set"
echo "  3. Run the DB migration once: python3 migrate.py"
