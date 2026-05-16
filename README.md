# manychat-smsoffice-bridge

A serverless bridge that lets [ManyChat](https://manychat.com) send SMS via [smsoffice.ge](https://smsoffice.ge) — deployed as Google Cloud Functions on the free tier.

For the complete zero-to-production setup, GitHub Actions deployment, and ManyChat usage guide, see [docs/SETUP_AND_MANYCHAT_USAGE.md](docs/SETUP_AND_MANYCHAT_USAGE.md).

## What it does

```
ManyChat External Request
        │ POST { phone, content, reference }
        ▼
┌─────────────────────────┐
│  send_sms (Cloud Func)  │  ← normalizes phone, calls smsoffice
└─────────────────────────┘
        │
        ▼
   smsoffice.ge API
        │
        ▼ (later, async)
┌─────────────────────────────┐
│  sms_callback (Cloud Func)  │  ← receives delivery status
└─────────────────────────────┘
```

- Normalizes Georgian phone numbers from ManyChat's E.164 format (`+995577123456`) to smsoffice format (`995577123456`).
- Authenticates ManyChat requests with a shared secret header.
- Maps smsoffice and validation failures into HTTP 200 JSON responses ManyChat can branch on.
- Receives delivery callbacks from smsoffice (logged to Cloud Logging by default).

## Cost

Designed for [Cloud Run functions](https://cloud.google.com/functions/pricing) / Cloud Functions 2nd gen request-based billing. The current [Cloud Run pricing](https://cloud.google.com/run/pricing) free tier includes 2M requests, 180k vCPU-seconds, and 360k GiB-seconds per month on Tier 1 pricing. This project uses request-time compute only, 256Mi memory, zero minimum instances, and a small max instance cap by default.

Secret Manager's free tier currently covers 6 active secret versions and 10k access operations per month. Cloud Build currently includes 2,500 free build-minutes per month, and Artifact Registry storage is free up to 0.5 GB. Keep old function images cleaned up and avoid enabling paid vulnerability scanning if the goal is near-$0 operation.

Tiny charges are still possible for outbound internet data transfer, usage above free limits, or SMS messages themselves. The code path is intentionally small enough that typical Messenger-funnel traffic should stay inside the serverless free-tier allowances.

## Prerequisites

- A GCP project with billing enabled (the free tier still requires a billing account).
- `gcloud` CLI installed and authenticated.
- A smsoffice.ge account with:
  - API key from [profile/integration](https://smsoffice.ge/you/profile/integration)
  - An **approved** sender ID under [shortnames](https://smsoffice.ge/you/shortnames/) (required, or you get `ErrorCode: 150`)
- A ManyChat **Pro** account (External Request action is Pro-only).

## Local development

```bash
cp .env.example .env
# fill in SMSOFFICE_API_KEY, MANYCHAT_SHARED_SECRET

make install
make test
make run    # serves send_sms on http://localhost:8080
make run-cb # serves sms_callback on http://localhost:8081, no .env required
```

Test locally:

```bash
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -H "X-Auth-Token: $MANYCHAT_SHARED_SECRET" \
  -d '{
    "phone": "+995577123456",
    "content": "Test from local",
    "reference": "local-test-1"
  }'
```

## Deployment With GitHub Actions

Recommended path: do the one-time Google Cloud bootstrap locally, then every push to `master` deploys automatically through GitHub Actions.

```bash
PROJECT_ID=your-project-id
REPO=otarza/manychat-smsoffice-bridge
REGION=europe-west1
SMSOFFICE_SENDER=YourApprovedSender

gcloud config set project $PROJECT_ID

gcloud services enable \
  cloudfunctions.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  iam.googleapis.com \
  artifactregistry.googleapis.com

# Store secrets
echo -n "YOUR_SMSOFFICE_KEY" | gcloud secrets create smsoffice-key --data-file=-
openssl rand -hex 32 | tr -d '\n' | gcloud secrets create manychat-secret --data-file=-
```

Create a deployer service account for GitHub Actions:

```bash
DEPLOY_SA="github-actions-deployer@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create github-actions-deployer \
  --display-name="GitHub Actions deployer"

for role in \
  roles/cloudfunctions.admin \
  roles/run.admin \
  roles/iam.serviceAccountAdmin \
  roles/iam.serviceAccountUser \
  roles/secretmanager.admin \
  roles/artifactregistry.admin \
  roles/cloudbuild.builds.editor \
  roles/serviceusage.serviceUsageConsumer
do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${DEPLOY_SA}" \
    --role="$role"
done
```

Set up GitHub OIDC / Workload Identity Federation so GitHub Actions can deploy without a long-lived JSON key:

```bash
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

gcloud iam workload-identity-pools create github \
  --project="$PROJECT_ID" \
  --location="global" \
  --display-name="GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc github \
  --project="$PROJECT_ID" \
  --location="global" \
  --workload-identity-pool="github" \
  --display-name="GitHub Actions provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository=='${REPO}' && assertion.ref=='refs/heads/master'"

gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" \
  --project="$PROJECT_ID" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/subject/repo:${REPO}:ref:refs/heads/master"
```

Add these GitHub repository variables under **Settings → Secrets and variables → Actions → Variables**:

| Variable | Value |
|---|---|
| `GCP_PROJECT_ID` | your Google Cloud project ID |
| `GCP_REGION` | `europe-west1` |
| `GCP_WIF_PROVIDER` | `projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github` |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | `github-actions-deployer@PROJECT_ID.iam.gserviceaccount.com` |
| `SMSOFFICE_SENDER` | your approved smsoffice sender |
| `MAX_INSTANCES` | `5` |

If you use GitHub CLI, you can set them with:

```bash
gh variable set GCP_PROJECT_ID --body "$PROJECT_ID"
gh variable set GCP_REGION --body "$REGION"
gh variable set GCP_WIF_PROVIDER --body "projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/providers/github"
gh variable set GCP_DEPLOY_SERVICE_ACCOUNT --body "$DEPLOY_SA"
gh variable set SMSOFFICE_SENDER --body "$SMSOFFICE_SENDER"
gh variable set MAX_INSTANCES --body "5"
```

After that, push to `master` or run **Actions → Deploy → Run workflow**. The workflow runs Ruff and pytest first, then deploys two Cloud Functions: `send-sms` and `sms-callback`. The deploy script creates separate runtime service accounts, grants Secret Manager access only to `send-sms`, sets minimum instances to zero, and prints both URLs in the action log.

Manual deployment still works from a logged-in machine:

```bash
SMSOFFICE_SENDER=YourApprovedSender make deploy
```

To retrieve the ManyChat shared secret (you need it for the ManyChat config):

```bash
gcloud secrets versions access latest --secret=manychat-secret
```

## ManyChat configuration

In your flow, add **Action → External Request**:

| Field | Value |
|---|---|
| Method | `POST` |
| URL | `<send-sms function URL from deploy output>` |
| Header | `Content-Type: application/json` |
| Header | `X-Auth-Token: <value from manychat-secret>` |
| Body | JSON (see below) |

Body:

```json
{
  "phone": "{{phone}}",
  "content": "Your message in Georgian or English",
  "reference": "{{user_id}}-{{message_id}}"
}
```

**Response mapping** — map these into custom fields so flow logic can branch:

| Response field | Custom field | Type |
|---|---|---|
| `success` | `sms_success` | Boolean |
| `error_code` | `sms_error_code` | Number |
| `message` | `sms_message` | Text |
| `error` | `sms_error` | Text |
| `reference` | `sms_reference` | Text |

ManyChat only maps response values reliably when the request returns `200 OK`, so authorized `send_sms` requests return `200` even for validation errors, smsoffice business errors, and smsoffice transport errors. Use `success` as the flow branch condition.

## Broadcast logging

The bridge writes structured JSON logs for each request, validation failure, smsoffice send attempt, send result, transport exception, and delivery callback. Message content and full phone numbers are not logged; logs include content length/hash, reference, masked destination, status, error code, and smsoffice message.

Watch logs live while sending a broadcast:

```bash
PROJECT_ID=manychat-smsoffice-bridge-otar REGION=europe-west1 make logs-tail
```

Show latest send results:

```bash
PROJECT_ID=manychat-smsoffice-bridge-otar REGION=europe-west1 make logs-results
```

Show latest failures:

```bash
PROJECT_ID=manychat-smsoffice-bridge-otar REGION=europe-west1 make logs-failures
```

## smsoffice callback (delivery receipts)

In your smsoffice.ge profile, set the callback URL to the `sms-callback` function URL from the deploy output. smsoffice will GET it with `reference`, `status`, `destination`, `timestamp`, `operator`. The function logs them to Cloud Logging; to persist them, edit `sms_callback` in `main.py` to write to Firestore / BigQuery / Sheets.

smsoffice limits `reference` to 20 UTF-8 bytes. If ManyChat sends a longer reference, the bridge hashes it to a stable 20-character value and returns that value in the `reference` response field. The callback will use the hashed value.

## Error codes

The `error_code` returned to ManyChat comes straight from smsoffice. For bridge-side validation or transport errors, `error_code` is `null` and `error` contains the local reason. Common smsoffice values:

| Code | Meaning |
|---|---|
| 0 | Accepted by smsoffice (not yet delivered — check callback) |
| 10 | Non-Georgian numbers in destination |
| 20 | Insufficient balance |
| 40 | Message exceeds 160 chars |
| 75 | All numbers are on stop list |
| 80 | Invalid API key |
| 150 | Sender ID not approved — fix in smsoffice profile |
| -100 | Transient — retry |

Full list: [smsoffice.ge/integration](https://smsoffice.ge/integration/).

## Project layout

```
.
├── .github/workflows/deploy.yml  # CI/CD: lint, test, deploy on master
├── .github/workflows/tests.yml   # CI: lint + pytest on pushes / PRs
├── docs/                         # setup, deployment, and usage guides
├── tests/                        # unit + handler tests
├── main.py                       # Cloud Functions entry points
├── smsoffice.py                  # API client
├── phone.py                      # Georgian phone normalization
├── requirements.txt              # runtime deps
├── requirements-dev.txt          # + pytest, ruff, responses
├── deploy.sh                     # gcloud deployment
├── Makefile                      # convenience commands
├── .env.example                  # local dev config template
├── .gcloudignore                 # exclude tests / dev files from deploy
└── .gitignore
```

## License

MIT
