# manychat-smsoffice-bridge

A serverless bridge that lets [ManyChat](https://manychat.com) send SMS via [smsoffice.ge](https://smsoffice.ge) — deployed as Google Cloud Functions on the free tier.

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
- Maps smsoffice error codes into a flat JSON response ManyChat can branch on.
- Receives delivery callbacks from smsoffice (logged to Cloud Logging by default).

## Cost

Designed to stay on the [Cloud Functions 2nd gen free tier](https://cloud.google.com/functions/pricing): 2M invocations and 400k GB-seconds per month. At typical Messenger-funnel volumes this runs at **$0/month**. Secret Manager free tier (6 active secret versions, 10k access ops/month) is also sufficient.

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

## Deployment

One-time GCP setup:

```bash
PROJECT_ID=your-project-id
gcloud config set project $PROJECT_ID

gcloud services enable \
  cloudfunctions.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com

# Store secrets
echo -n "YOUR_SMSOFFICE_KEY" | gcloud secrets create smsoffice-key --data-file=-
openssl rand -hex 32 | tr -d '\n' | gcloud secrets create manychat-secret --data-file=-

# Grant the compute default service account read access to the secrets
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for s in smsoffice-key manychat-secret; do
  gcloud secrets add-iam-policy-binding $s \
    --member="serviceAccount:${SA}" \
    --role="roles/secretmanager.secretAccessor"
done
```

Then deploy:

```bash
make deploy
```

This deploys two Cloud Functions, `send-sms` and `sms-callback`. Their URLs print at the end — save them.

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

## smsoffice callback (delivery receipts)

In your smsoffice.ge profile, set the callback URL to the `sms-callback` function URL from the deploy output. smsoffice will GET it with `reference`, `status`, `destination`, `timestamp`, `operator`. The function logs them to Cloud Logging; to persist them, edit `sms_callback` in `main.py` to write to Firestore / BigQuery / Sheets.

## Error codes

The `error_code` returned to ManyChat comes straight from smsoffice. Common values:

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
├── .github/workflows/tests.yml   # CI: lint + pytest on every push
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
