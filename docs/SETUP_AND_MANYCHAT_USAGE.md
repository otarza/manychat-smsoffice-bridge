# Setup And ManyChat Usage Guide

This guide documents the full setup for `manychat-smsoffice-bridge`: Google Cloud, GitHub Actions deployment, smsoffice configuration, ManyChat usage, and future maintenance.

The goal is simple: let ManyChat send SMS notifications to Georgian phone numbers through the smsoffice.ge API, with the bridge running on Google Cloud's serverless free-tier-friendly infrastructure.

## Architecture

```text
ManyChat Automation
  -> External Request: POST /send-sms
  -> Google Cloud Function: send_sms
  -> smsoffice.ge API
  -> Customer receives SMS

smsoffice delivery status
  -> Google Cloud Function: sms_callback
  -> Cloud Logging
```

The project deploys two Cloud Functions from the same source:

| Function | Purpose |
|---|---|
| `send-sms` | Receives ManyChat requests, validates/authenticates, normalizes phone numbers, calls smsoffice |
| `sms-callback` | Receives delivery status callbacks from smsoffice and returns `OK` |

## Important Concepts

- The smsoffice API key is stored in Google Secret Manager as `smsoffice-key`.
- The ManyChat auth token is stored in Google Secret Manager as `manychat-secret`.
- Do not store either secret in GitHub.
- GitHub Actions deploys through Google Workload Identity Federation, so there is no long-lived Google JSON key.
- `send-sms` is public but protected by the `X-Auth-Token` header.
- `sms-callback` is public and intentionally unauthenticated because smsoffice must call it.
- ManyChat custom fields store only the last SMS result for each contact.
- Final delivery statuses are currently logged in Cloud Logging only. They are not written back to ManyChat.

## What You Need

Before setup:

- A Google Cloud account with billing enabled.
- The Google Cloud CLI, `gcloud`.
- A GitHub repository containing this project.
- A smsoffice.ge API key.
- An approved smsoffice sender/shortname, for example `BitCamp`.
- A paid ManyChat plan with External Request access.

Useful docs:

- [Google Cloud CLI install](https://cloud.google.com/sdk/docs/install)
- [Cloud Functions deploy docs](https://cloud.google.com/functions/docs/deploy)
- [Secret Manager docs](https://cloud.google.com/secret-manager/docs/creating-and-accessing-secrets)
- [Google GitHub auth action](https://github.com/google-github-actions/auth)
- [ManyChat External Request docs](https://help.manychat.com/hc/en-us/articles/14281285374364-Dev-Tools-External-Request)
- [smsoffice integration docs](https://smsoffice.ge/integration/)

## 1. Create Or Select A Google Cloud Project

Project IDs are globally unique and cannot be renamed after creation.

Example project used during the original setup:

```bash
PROJECT_ID=manychat-smsoffice-bridge-otar
```

Create a new project if needed:

```bash
gcloud projects create "$PROJECT_ID" \
  --name="manychat-smsoffice-bridge"
```

Switch `gcloud` to the project:

```bash
gcloud config set project "$PROJECT_ID"
gcloud config get-value project
```

Link billing in the Google Cloud Console, or with:

```bash
gcloud billing accounts list

BILLING_ACCOUNT_ID=YOUR_BILLING_ACCOUNT_ID

gcloud billing projects link "$PROJECT_ID" \
  --billing-account="$BILLING_ACCOUNT_ID"
```

## 2. Define Local Setup Variables

Use your real values:

```bash
PROJECT_ID=manychat-smsoffice-bridge-otar
REGION=europe-west1
REPO=otarza/manychat-smsoffice-bridge
SMSOFFICE_SENDER=BitCamp
SMSOFFICE_API_KEY=your-real-smsoffice-api-key
```

`SMSOFFICE_SENDER` must be an approved sender in smsoffice.

## 3. Enable Google Cloud APIs

```bash
gcloud services enable \
  cloudfunctions.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  artifactregistry.googleapis.com \
  cloudresourcemanager.googleapis.com
```

## 4. Create Google Secret Manager Secrets

Create the smsoffice API key secret:

```bash
echo -n "$SMSOFFICE_API_KEY" | gcloud secrets create smsoffice-key \
  --replication-policy=automatic \
  --data-file=-
```

Create the ManyChat shared secret:

```bash
openssl rand -hex 32 | tr -d '\n' | gcloud secrets create manychat-secret \
  --replication-policy=automatic \
  --data-file=-
```

Verify:

```bash
gcloud secrets list
```

Expected:

```text
manychat-secret
smsoffice-key
```

To print the ManyChat token later:

```bash
gcloud secrets versions access latest \
  --project="$PROJECT_ID" \
  --secret=manychat-secret
```

## 5. Create The GitHub Actions Deployer

Create a deployer service account:

```bash
DEPLOY_SA="github-actions-deployer@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create github-actions-deployer \
  --display-name="GitHub Actions deployer"
```

Grant deployment roles:

```bash
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

Verify:

```bash
gcloud iam service-accounts describe "$DEPLOY_SA"
```

These roles are intentionally practical for first setup. They can be tightened later after deployment is stable.

## 6. Configure GitHub OIDC / Workload Identity

Get the project number:

```bash
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
echo "$PROJECT_NUMBER"
```

Create the pool:

```bash
gcloud iam workload-identity-pools create github \
  --project="$PROJECT_ID" \
  --location="global" \
  --display-name="GitHub Actions"
```

Create the GitHub provider:

```bash
gcloud iam workload-identity-pools providers create-oidc github \
  --project="$PROJECT_ID" \
  --location="global" \
  --workload-identity-pool="github" \
  --display-name="GitHub Actions provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository=='${REPO}' && assertion.ref=='refs/heads/master'"
```

Allow GitHub Actions on `master` to impersonate the deployer:

```bash
gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" \
  --project="$PROJECT_ID" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/subject/repo:${REPO}:ref:refs/heads/master"
```

Workload Identity permissions can take a few minutes to propagate. If the first deploy fails with an auth error, wait and rerun.

## 7. Add GitHub Actions Variables

In GitHub:

```text
Repository -> Settings -> Secrets and variables -> Actions -> Variables
```

Add repository variables:

| Variable | Example value |
|---|---|
| `GCP_PROJECT_ID` | `manychat-smsoffice-bridge-otar` |
| `GCP_REGION` | `europe-west1` |
| `GCP_WIF_PROVIDER` | `projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github` |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | `github-actions-deployer@PROJECT_ID.iam.gserviceaccount.com` |
| `SMSOFFICE_SENDER` | `BitCamp` |
| `MAX_INSTANCES` | `5` |

Print the exact values:

```bash
echo "GCP_PROJECT_ID=$PROJECT_ID"
echo "GCP_REGION=$REGION"
echo "GCP_WIF_PROVIDER=projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/providers/github"
echo "GCP_DEPLOY_SERVICE_ACCOUNT=$DEPLOY_SA"
echo "SMSOFFICE_SENDER=$SMSOFFICE_SENDER"
echo "MAX_INSTANCES=5"
```

Optional GitHub CLI version:

```bash
gh variable set GCP_PROJECT_ID --repo "$REPO" --body "$PROJECT_ID"
gh variable set GCP_REGION --repo "$REPO" --body "$REGION"
gh variable set GCP_WIF_PROVIDER --repo "$REPO" --body "projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/providers/github"
gh variable set GCP_DEPLOY_SERVICE_ACCOUNT --repo "$REPO" --body "$DEPLOY_SA"
gh variable set SMSOFFICE_SENDER --repo "$REPO" --body "$SMSOFFICE_SENDER"
gh variable set MAX_INSTANCES --repo "$REPO" --body "5"
```

No GitHub secrets are needed for the current deployment.

## 8. Deploy

Automatic deployment:

```text
GitHub -> Actions -> Deploy -> Run workflow -> Branch: master
```

The workflow:

1. Checks out the repo.
2. Installs Python dependencies.
3. Runs Ruff.
4. Runs pytest.
5. Authenticates to Google Cloud with Workload Identity Federation.
6. Runs `./deploy.sh`.

Deployment also runs automatically on pushes to `master`.

Manual local deployment still works:

```bash
SMSOFFICE_SENDER=BitCamp make deploy
```

## 9. Get Function URLs

From the GitHub Actions `Deploy` log, copy the two URLs printed at the end.

Or run:

```bash
gcloud functions describe send-sms \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --gen2 \
  --format='value(serviceConfig.uri)'

gcloud functions describe sms-callback \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --gen2 \
  --format='value(serviceConfig.uri)'
```

Save:

| URL | Use |
|---|---|
| `send-sms` | ManyChat External Request URL |
| `sms-callback` | smsoffice delivery callback URL |

## 10. Test The Deployed Function

Get the ManyChat token:

```bash
MANYCHAT_SECRET=$(gcloud secrets versions access latest \
  --project="$PROJECT_ID" \
  --secret=manychat-secret)
```

Use your real test phone number:

```bash
SEND_SMS_URL=PASTE_SEND_SMS_URL

curl -X POST "$SEND_SMS_URL" \
  -H "Content-Type: application/json" \
  -H "X-Auth-Token: $MANYCHAT_SECRET" \
  -d '{
    "phone": "+995577123456",
    "content": "Test SMS from deployed bridge",
    "reference": "test-1"
  }'
```

Expected success shape:

```json
{
  "success": true,
  "error_code": 0,
  "message": "queued",
  "destination": "995577123456",
  "reference": "test-1"
}
```

The actual `message` text comes from smsoffice and may differ.

## 11. Configure smsoffice Callback

In smsoffice.ge, open the integration/profile callback settings and set the callback URL to the deployed `sms-callback` URL.

The callback function returns:

```text
OK
```

smsoffice expects that literal response.

Current callback behavior:

- Logs `reference`, `status`, `reason`, `destination`, `timestamp`, and `operator`.
- Does not store delivery history anywhere.
- Does not update ManyChat custom fields.

## 12. ManyChat Direct External Request Setup

Use this when you want to add SMS sending directly inside one automation.

In ManyChat:

```text
Automation -> open flow -> Action -> Automation -> Make External Request
```

Request:

| Setting | Value |
|---|---|
| Method | `POST` |
| URL | Deployed `send-sms` URL |
| Header | `Content-Type: application/json` |
| Header | `X-Auth-Token: value of manychat-secret` |

Body:

```json
{
  "phone": "{{phone}}",
  "content": "Your SMS text here",
  "reference": "{{user_id}}"
}
```

If ManyChat's variable picker shows a different phone token, use the picker value.

## 13. ManyChat Custom Fields

Create these ManyChat User Fields before response mapping:

| Field | Type | Purpose |
|---|---|---|
| `sms_success` | Boolean | Whether the latest SMS request was accepted |
| `sms_error_code` | Number | smsoffice error code, if any |
| `sms_message` | Text | smsoffice/bridge response message |
| `sms_error` | Text | local bridge error key, if any |
| `sms_reference` | Text | reference sent to smsoffice |
| `sms_destination` | Text | normalized destination phone |

Map response fields:

| JSONPath | Custom field |
|---|---|
| `$.success` | `sms_success` |
| `$.message` | `sms_message` |
| `$.error` | `sms_error` |
| `$.error_code` | `sms_error_code` |
| `$.reference` | `sms_reference` |
| `$.destination` | `sms_destination` |

Important: ManyChat's test request can show a successful HTTP response without saving mapped fields. To verify field mapping, trigger the automation as a real/preview contact.

## 14. Branching In ManyChat

After the External Request, add a condition:

```text
sms_success is true
```

Recommended branches:

```text
true
  -> continue normal flow

false
  -> tag contact
  -> notify admin
  -> show fallback message
```

Do not branch on HTTP status. The bridge returns HTTP 200 for authorized validation and smsoffice failures so ManyChat can map the response.

Authentication or wrong-method failures still return HTTP errors.

## 15. Reusable "Widget" Pattern In ManyChat

ManyChat does not provide a literal custom widget for this simple setup. The practical reusable pattern is a utility automation.

Create input fields:

| Field | Type |
|---|---|
| `sms_content_to_send` | Text |
| `sms_reference_to_send` | Text |

Create an automation named:

```text
UTIL - Send SMS
```

Inside it, add the same External Request, but use:

```json
{
  "phone": "{{phone}}",
  "content": "{{sms_content_to_send}}",
  "reference": "{{sms_reference_to_send}}"
}
```

In any other automation:

1. Set `sms_content_to_send`.
2. Set `sms_reference_to_send`.
3. Start automation: `UTIL - Send SMS`.
4. Branch on `sms_success`.

Example:

```text
Main automation
  -> Set sms_content_to_send = "Your booking is confirmed"
  -> Set sms_reference_to_send = "booking-{{user_id}}"
  -> Start Automation: UTIL - Send SMS
  -> Condition: sms_success is true?
```

This behaves like a reusable SMS widget.

Caveat: these input fields are stored on the contact. If the same contact triggers two SMS utility calls at the exact same time, the inputs can overwrite each other. For normal ManyChat flows this is usually fine.

## 16. What The Response Means

Example success:

```json
{
  "success": true,
  "error_code": 0,
  "message": "queued",
  "destination": "995577123456",
  "reference": "test-1"
}
```

`success: true` means smsoffice accepted/queued the SMS. It does not guarantee final delivery to the phone.

Example bridge-side validation failure:

```json
{
  "success": false,
  "error": "invalid_phone",
  "error_code": null,
  "message": "invalid phone",
  "detail": "Not a valid Georgian mobile number..."
}
```

Example smsoffice failure:

```json
{
  "success": false,
  "error_code": 20,
  "message": "Insufficient balance",
  "destination": "995577123456",
  "reference": "test-1"
}
```

## 17. Phone And Message Rules

The bridge accepts common Georgian formats:

| Input | Normalized |
|---|---|
| `+995577123456` | `995577123456` |
| `00995577123456` | `995577123456` |
| `995577123456` | `995577123456` |
| `577123456` | `995577123456` |
| `0577123456` | `995577123456` |

Only Georgian mobile numbers matching `9955XXXXXXXX` are accepted.

Message rules:

- Max content length: 1000 characters.
- Georgian and English text are supported.
- The `reference` sent to smsoffice is limited to 20 UTF-8 bytes.
- Long references are hashed to a stable 20-character value and returned in the response.

## 18. Logs And Monitoring

The bridge emits structured JSON logs for broadcast monitoring.

Logged send events:

| Event | Meaning |
|---|---|
| `send_request_received` | Authorized ManyChat request was received |
| `send_validation_failed` | Request could not be sent because input was missing, invalid, or too long |
| `send_attempt` | Bridge is calling smsoffice |
| `send_result` | smsoffice returned a parsed result |
| `send_exception` | Network/non-JSON smsoffice error |
| `delivery_callback` | smsoffice called the callback URL with delivery status |

Logs intentionally do not include SMS content or full phone numbers. They include:

- `request_id`
- `reference`
- `destination_masked`
- `content_len`
- `content_hash`
- `success`
- `error`
- `error_code`
- `message`
- callback `status`, `reason`, `timestamp`, and `operator`

Watch live logs while sending a broadcast:

```bash
PROJECT_ID=manychat-smsoffice-bridge-otar REGION=europe-west1 make logs-tail
```

The raw JSON live tail is complete, but it can be noisy. For broadcast monitoring, this compact table is easier to read. It uses `scripts/tail_logs.py` to poll Cloud Logging every couple seconds and print one readable row per event:

```bash
PROJECT_ID=manychat-smsoffice-bridge-otar REGION=europe-west1 make logs-broadcast-tail
```

This includes send results, send failures, validation failures, and delivery callbacks in one table.

Watch only live send results:

```bash
PROJECT_ID=manychat-smsoffice-bridge-otar REGION=europe-west1 make logs-results-tail
```

Watch only live failures:

```bash
PROJECT_ID=manychat-smsoffice-bridge-otar REGION=europe-west1 make logs-failures-tail
```

This uses:

```bash
gcloud beta logging tail
```

If `gcloud` asks to install beta components, accept it.

Show latest send results:

```bash
PROJECT_ID=manychat-smsoffice-bridge-otar REGION=europe-west1 make logs-results
```

Show latest failures:

```bash
PROJECT_ID=manychat-smsoffice-bridge-otar REGION=europe-west1 make logs-failures
```

Read raw send function logs:

```bash
gcloud functions logs read send-sms \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --gen2 \
  --limit=50
```

Read raw callback logs:

```bash
gcloud functions logs read sms-callback \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --gen2 \
  --limit=50
```

Recommended Google Cloud setup:

- Create a billing budget alert.
- Keep max instances low unless real traffic requires more.
- Keep minimum instances at zero.
- Clean up old Artifact Registry images if storage grows.

During a 500-contact broadcast, keep one terminal open with:

```bash
make logs-broadcast-tail
```

And another terminal for summarized results:

```bash
make logs-results
make logs-failures
```

## 19. Updating The App

Normal update flow:

1. Edit code.
2. Run:

```bash
make test
make lint
```

3. Commit and push to `master`.
4. GitHub Actions deploys automatically.

Manual deployment:

```bash
SMSOFFICE_SENDER=BitCamp make deploy
```

## 20. Rotating Secrets

Rotate smsoffice API key:

```bash
echo -n "NEW_SMSOFFICE_API_KEY" | gcloud secrets versions add smsoffice-key \
  --project="$PROJECT_ID" \
  --data-file=-
```

Rotate ManyChat secret:

```bash
openssl rand -hex 32 | tr -d '\n' | gcloud secrets versions add manychat-secret \
  --project="$PROJECT_ID" \
  --data-file=-
```

Then update the ManyChat `X-Auth-Token` header to the new value:

```bash
gcloud secrets versions access latest \
  --project="$PROJECT_ID" \
  --secret=manychat-secret
```

Redeploying is usually not required for `latest` secret references, but new Cloud Run instances must start before they see changed secret environment values. A redeploy is the simplest way to force that.

## 21. Troubleshooting

### GitHub deploy succeeds but ManyChat call fails

Check:

- ManyChat URL is the `send-sms` URL, not `sms-callback`.
- `X-Auth-Token` matches `manychat-secret`.
- Request method is `POST`.
- Body is valid JSON.

### ManyChat response mapping fields stay empty

The External Request test panel does not always save mapped values. Trigger the automation as a real/preview contact and inspect the contact's custom fields.

### `sms_success` is false and `sms_error` is `invalid_phone`

The phone is missing, not Georgian, or not a Georgian mobile number.

### `sms_success` is false and `sms_error_code` is `20`

smsoffice balance is insufficient.

### `sms_success` is false and `sms_error_code` is `150`

The sender ID is not approved or does not match smsoffice configuration.

### GitHub Actions auth fails

Check:

- GitHub variable `GCP_WIF_PROVIDER`.
- GitHub variable `GCP_DEPLOY_SERVICE_ACCOUNT`.
- Workload Identity provider condition uses the correct repo and branch.
- Wait a few minutes after creating Workload Identity.

### Cloud Function deploy fails with secret access errors

The deploy script grants Secret Manager access to the runtime service account for `send-sms`. Confirm the secrets exist:

```bash
gcloud secrets list --project="$PROJECT_ID"
```

Then rerun deployment.

### GitHub Actions warning about Node.js runtime

If the deploy job is green, this warning is not blocking. Update GitHub action versions later when upstream actions publish newer runtime versions.

## 22. Current Limitations

- ManyChat custom fields store only the last SMS result per contact.
- Delivery callback status is logged, not stored.
- No retry queue is implemented.
- No admin dashboard is implemented.
- Only Georgian mobile numbers are accepted.

Good future upgrades:

- Store send/callback history in Firestore or BigQuery.
- Add a Google Sheet export for non-technical reporting.
- Add retry logic for transient smsoffice failures.
- Add alerting for repeated failures or low smsoffice balance.
