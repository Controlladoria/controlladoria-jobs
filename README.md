# ControlladorIA Jobs

Background document processing and scheduled maintenance tasks for the ControlladorIA platform. Runs on **AWS Lambda** (containerized) with **Celery** as an alternative for self-hosted deployments.

## Lambda Functions

| Function | Trigger | Purpose |
|----------|---------|---------|
| `document-processing` | SQS | AI extraction from uploaded documents |
| `cleanup-files` | EventBridge (daily 2AM BRT) | Delete files older than retention period |
| `cleanup-tokens` | EventBridge (every 6h) | Clear expired verification tokens |
| `retry-documents` | EventBridge (daily 2AM BRT) | Retry failed document processing |

## Tech Stack

- **Python 3.12** on AWS Lambda (Docker container)
- **AI**: Gemini Flash Lite / Amazon Nova / GPT-5.4 Nano (3-tier failover)
- **Config**: AWS SSM Parameter Store (production) / `.env` (local)
- **Database**: PostgreSQL (shared with API)

## Local Development

```bash
pip install -r requirements.txt
cp .env.example .env              # configure keys (or copy from API)

# Run as Celery worker
celery -A celery_app worker -l info -c 4
```

## Deployment

Deployed via **GitHub Actions** to **AWS Lambda** (us-east-2):
- Docker image pushed to ECR
- Lambda functions created/updated via AWS CLI
- SQS triggers and EventBridge schedules managed in pipeline
- Config loaded from SSM at cold start

**Dev**: auto-deploy on push to `main`
**Prod**: manual `workflow_dispatch` (type "deploy" to confirm)
