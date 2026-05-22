# controlladoria-jobs

Asynchronous document processing and scheduled maintenance tasks for the ControlladorIA platform. Runs on **AWS Lambda** (containerized via Docker/ECR) with **Celery + Redis** as an alternative for self-hosted deployments.

Shares the database models, `StructuredDocumentProcessor`, and configuration system with `controlladoria-api` — the two repos are kept in sync.

- **Runtime:** Python 3.12 on AWS Lambda (Docker container image)
- **Region:** us-east-2
- **Config source (prod):** AWS SSM Parameter Store (`/controlladoria/prod/worker/*`)
- **Config source (dev):** `.env` file

---

## Lambda Functions

| Function Name | Handler | Trigger | Memory | Timeout | Purpose |
|---------------|---------|---------|--------|---------|---------|
| `controlladoria-worker-document-processing-{env}` | `handlers.process_document.handler` | SQS | 1024MB | 900s | AI extraction from uploaded docs |
| `controlladoria-worker-cleanup-files-{env}` | `handlers.cleanup_files.handler` | EventBridge daily 05:00 UTC (02:00 BRT) | 256MB | 300s | Delete files past retention period |
| `controlladoria-worker-cleanup-tokens-{env}` | `handlers.cleanup_tokens.handler` | EventBridge every 6h | 256MB | 60s | Purge expired auth tokens |
| `controlladoria-worker-retry-documents-{env}` | `handlers.retry_documents.handler` | EventBridge daily 05:00 UTC | 256MB | 300s | Retry documents stuck in PROCESSING |

---

## Document Processing Flow

```
User uploads file → controlladoria-api
  └── File saved to S3
      └── SQS message sent: { document_id, file_path }
          └── Lambda: handlers/process_document.py
              ├── Download file from S3 to /tmp
              ├── Open DB session
              ├── Set document status → PROCESSING
              ├── StructuredDocumentProcessor.process()
              │     ├── Detect format (PDF / Excel / XML / OFX / image)
              │     ├── AI extraction call (Gemini → Nova → GPT cascade)
              │     ├── Parse transactions: date, amount, description, type, category
              │     ├── OFX: detect same-owner transfers (TRNTYPE=XFER, "MESMA TITULARIDADE")
              │     ├── Batch categorize remaining "nao_categorizado" items
              │     └── AI audit pass: review all categories before user sees rows
              ├── Create DocumentValidationRows in DB
              └── Set document status → PENDING_VALIDATION
```

SQS batch size is 1 (each document is processed independently). Concurrency: 10 (dev) / 50 (prod). DLQ retries 3 times before dead-lettering.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.12 |
| Containerization | Docker (ECR image) |
| Queue | AWS SQS (FIFO-compatible, visibility timeout 900s) |
| Scheduling | AWS EventBridge |
| AI — primary | Gemini Flash Lite (`gemini-flash-lite-latest`) |
| AI — secondary | Nova 2 Lite via AWS Bedrock (`us.amazon.nova-2-lite-v1:0`) |
| AI — fallback | GPT-5.4 Nano (`gpt-5.4-nano`) |
| Database | PostgreSQL 16 (shared with API) |
| File storage | AWS S3 |
| Config (prod) | AWS SSM Parameter Store |
| Alternative | Celery + Redis (for self-hosted deployments) |

---

## AI Failover

```
Gemini Flash Lite  →  Nova 2 Lite (Bedrock)  →  GPT-5.4 Nano
   (primary)             (backup)                  (fallback)
```

- Keys are pooled per provider (comma-separated in SSM/env).
- A key is marked unhealthy after 3 consecutive errors, recovers after 5 minutes.
- `AI_FAILOVER_ENABLED=true` triggers automatic cross-provider switch when all keys for the active provider are unhealthy.
- Nova uses IAM credentials (no API key), same `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` as S3.

---

## SSM Parameter Store (Production)

All Lambda config is loaded from SSM at cold start. Prefix: `/controlladoria/prod/worker/`

| Parameter | Type | Description |
|-----------|------|-------------|
| `DATABASE_URL` | SecureString | PostgreSQL connection string |
| `JWT_SECRET_KEY` | SecureString | Token signing key (shared with API) |
| `ENCRYPTION_KEY` | SecureString | Fernet key for MFA secrets |
| `AI_PROVIDER` | String | `gemini` (primary) |
| `GEMINI_API_KEYS` | SecureString | Comma-separated Gemini keys |
| `GEMINI_MODEL` | String | `gemini-flash-lite-latest` |
| `NOVA_MODEL` | String | `us.amazon.nova-2-lite-v1:0` |
| `NOVA_REGION` | String | `us-east-2` |
| `OPENAI_API_KEYS` | SecureString | Comma-separated OpenAI keys |
| `OPENAI_MODEL` | String | `gpt-5.4-nano` |
| `AI_FAILOVER_ENABLED` | String | `true` |
| `S3_BUCKET_NAME` | String | Document storage bucket |
| `USE_S3` | String | `true` |
| `SQS_DOCUMENT_QUEUE_URL` | String | SQS queue URL |
| `STRIPE_API_KEY` | SecureString | Stripe key |
| `RESEND_API_KEY` | SecureString | Email key |
| `FRONTEND_URL` | String | Customer UI URL |
| `ENVIRONMENT` | String | `production` |

---

## Celery (Self-Hosted Alternative)

For deployments without Lambda, the same processing runs via Celery workers:

```bash
# Start worker
celery -A celery_app worker -l info -c 4

# Queues
#   documents — single document processing
#   bulk      — bulk upload batches
```

Celery config: Redis broker, America/Sao_Paulo timezone, 10-minute task time limit, prefetch 1.

---

## Local Development

```bash
# 1. Install dependencies (same as API)
pip install -r requirements.txt

# 2. Configure (copy from API .env or create minimal)
cp .env.example .env

# 3. Run as Celery worker (requires Redis)
celery -A celery_app worker -l info -c 4

# Or invoke a handler directly for testing:
python -c "
from handlers.process_document import handler
handler({'Records': [{'body': '{\"document_id\": 1, \"file_path\": \"test.pdf\"}'}]}, None)
"
```

---

## Deployment

CI/CD via **GitHub Actions** (`deploy-dev.yml` / `deploy-prod.yml`):

```
Push to main  →  deploy-dev.yml   →  ECR (controlladoria-worker-dev)  →  Lambda update
workflow_dispatch ("deploy")  →  deploy-prod.yml  →  ECR (controlladoria-worker-prod)  →  Lambda update
```

The workflow:
1. Builds Docker image, tags with git SHA, pushes to ECR
2. Creates Lambda functions if they don't exist (using `LAMBDA_EXECUTION_ROLE_ARN`)
3. Updates function code + config on existing functions
4. Waits for all functions to finish updating
5. Invalidates warm instances (bumps `DEPLOY_SHA` env var)
6. Wires SQS event source mapping (batch size 1, max concurrency 50 in prod)
7. Creates EventBridge rules for scheduled functions (idempotent — skips if already exist)
8. Cleans up old ECR images (keeps 5 most recent)

### Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `AWS_ACCESS_KEY_ID` | IAM user with ECR + Lambda + SQS + EventBridge permissions |
| `AWS_SECRET_ACCESS_KEY` | Corresponding secret |
| `LAMBDA_EXECUTION_ROLE_ARN` | IAM role ARN for Lambda execution |
| `DEV_SQS_DOCUMENT_PROCESSING_ARN` | ARN of dev SQS queue |
| `PROD_SQS_DOCUMENT_PROCESSING_ARN` | ARN of prod SQS queue |

### Required AWS Resources (pre-created)

| Resource | Details |
|----------|---------|
| ECR repositories | `controlladoria-worker-dev`, `controlladoria-worker-prod` (auto-created by workflow) |
| SQS queues | `controlladoria-document-processing-{dev,prod}` — visibility timeout 900s, DLQ maxReceiveCount=3 |
| IAM execution role | Permissions: ECR pull, S3 GetObject/PutObject, SQS ReceiveMessage/DeleteMessage, SSM GetParameter, Bedrock InvokeModel, CloudWatch Logs |
| S3 bucket | Shared with API |
| SSM parameters | All `/controlladoria/prod/worker/*` entries (populated manually) |
