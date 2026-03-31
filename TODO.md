# controlladoria-jobs — TODO

## Future: Real-time Notifications

When a document finishes processing (Lambda completes), the user currently
has to refresh/poll the documents list to see the result. Improve UX with
real-time notifications.

### Options to evaluate:
1. **AWS AppSync + WebSocket** — managed GraphQL subscriptions
2. **Pusher / Ably** — third-party real-time service (~$0 at low scale)
3. **Server-Sent Events (SSE)** — API holds connection, Lambda writes to shared DB/Redis, API streams updates
4. **Polling with exponential backoff** — simplest, already partially works

### Implementation sketch (Pusher, simplest):
- Lambda: after processing, call Pusher API to notify channel `user-{user_id}`
- Frontend: subscribe to Pusher channel, update document status in real-time
- Cost: free tier covers 200k messages/day

## Future: Lambda Layers
- Create a shared Lambda Layer with common dependencies (sqlalchemy, boto3, etc.)
- Reduces deployment package size for each handler
- Share database models across handlers without duplication

## Future: SAM / CDK Template
- Create AWS SAM or CDK template for infrastructure-as-code
- Define SQS queue, Lambda functions, EventBridge rules
- Enable one-command deployment
