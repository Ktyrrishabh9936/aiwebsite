# AWS Lambda deployment (Arevei backend)

This deployment replaces the Vercel backend with an AWS Lambda container image.
Keep the React frontend on Vercel. Lambda Function URL serves the existing
FastAPI API, and EventBridge Scheduler invokes Lambda directly every minute.

## 1. Prerequisites

- AWS region: **Asia Pacific (Mumbai) — `ap-south-1`**.
- Docker Desktop running locally.
- AWS CLI installed and signed in with permissions for ECR, Lambda, IAM, and
  EventBridge Scheduler. Run `aws configure` if the CLI has not been configured.
- A production MongoDB URI that permits network connections from AWS.

Do not upload `backend/.env` and do not commit any secret.

## 2. Create an ECR repository

1. In AWS Console, open **Elastic Container Registry (ECR)**.
2. Choose **Repositories** > **Create repository**.
3. Select **Private**, name it `arevei-backend`, then create it.
4. Open the repository and choose **View push commands**.

In PowerShell, open `backend` and run the commands AWS displays. They have this
shape (replace `ACCOUNT_ID` with the number from your ECR page):

```powershell
cd C:\Users\Wave\Documents\Arevei\aiwebsite\backend
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com
docker build -t arevei-backend .
docker tag arevei-backend:latest ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com/arevei-backend:latest
docker push ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com/arevei-backend:latest
```

## 3. Create the Lambda function

1. Open **AWS Lambda** > **Create function**.
2. Select **Container image**.
3. Function name: `arevei-backend`.
4. Select the `arevei-backend:latest` ECR image.
5. Select architecture **x86_64**, then create the function.
6. In **Configuration** > **General configuration**, set Memory to `1024 MB` and
   Timeout to `30 seconds`.

## 4. Add Lambda configuration

In Lambda **Configuration** > **Environment variables**, add the values used by
the production backend. Copy the active production values one-by-one from
`backend/.env` or the old backend host; do not upload the `.env` file itself.

These unused integrations do not need to be copied:

```text
EMERGENT_LLM_KEY
OPENROUTER_API_KEY
NVIDIA_NIM_API_KEY
OPENAI_API_KEY
DAYTONA_API_KEY
DAYTONA_TARGET
VERCEL_CLIENT_ID
VERCEL_CLIENT_SECRET
GITHUB_APP_ID
GITHUB_APP_SLUG
GITHUB_PRIVATE_KEY
```

Add these two deployment values as well:

```text
CORS_ORIGINS=https://ainativemanager.vercel.app
DISABLE_BACKGROUND_JOBS=true
```

The active configuration totals about 2 KB without those unused integrations,
which is within Lambda's 4 KB environment-variable limit.

Leave Lambda outside a custom VPC unless you deliberately configure a NAT
Gateway. It needs outbound internet access for MongoDB Atlas and web push.

## 5. Create a Lambda Function URL

1. In the Lambda function, open **Configuration** > **Function URL**.
2. Choose **Create function URL**.
3. Auth type: **NONE**.
4. Enable CORS, with:
   - Allowed origin: `https://ainativemanager.vercel.app`
   - Methods: `GET, POST, PUT, PATCH, DELETE, OPTIONS`
   - Headers: `Content-Type, Authorization, X-App-Timezone`
5. Create it and copy the generated URL.

The application keeps its own user authentication. The scheduled invocation is
protected by an AWS IAM execution role, not a public endpoint.

The Function URL is an acceptable bootstrap endpoint, but it is public and must
not be treated as a secret. For production form sharing, put an **API Gateway
HTTP API** with an ACM-backed custom domain such as `forms.arevei.com` in front
of this Lambda. HTTP API is the preferred default here because it is lower-cost
and lower-latency than REST API. If you need AWS WAF, per-client API keys/usage
plans, or gateway request validation, use a Regional **REST API** instead (or
CloudFront + WAF in front of the Function URL).

Keep the application controls even after adding a front door: exact CORS
origins, form-domain allowlists, request-size validation, honeypot checks and
per-IP/per-form rate limits. Hiding the Lambda hostname alone is not security.

## 6. Switch the Vercel frontend

In the Vercel project that hosts `ainativemanager.vercel.app`:

1. Open **Settings** > **Environment Variables**.
2. Set `REACT_APP_BACKEND_URL` to the Lambda Function URL (no trailing slash).
3. After the custom forms domain is ready, set backend `PUBLIC_BASE_URL` to its
   origin (for example `https://forms.arevei.com`) and frontend
   `REACT_APP_PUBLIC_FORM_BASE_URL` to its API base (for example
   `https://forms.arevei.com/api`). Share links and embed snippets will then use
   the branded domain instead of the Function URL.
4. Apply the frontend values to **Production**.
5. Redeploy the frontend.

Test normal sign-in and CRM operations before changing the scheduler.

## 7. Schedule follow-up push delivery

1. Open **EventBridge Scheduler** > **Create schedule**.
2. Name: `arevei-followup-push-dispatch`.
3. Select a recurring rate schedule: **1 minute**; flexible time window: **Off**.
4. Target: **AWS Lambda Invoke**.
5. Select the `arevei-backend` Lambda function.
6. Set the JSON payload to:

```json
{"action":"dispatch_due_followups"}
```

7. Under execution role, choose **Create new role for this schedule** and give
   it a name such as `arevei-scheduler-invoke-lambda`.
8. Configure 3 retries and create the schedule.

This direct AWS-to-AWS invocation is protected by IAM. Do not use a public
HTTP scheduler target and do not put any scheduler secret in the browser.

## 8. Verify end-to-end

1. In the live app, enable follow-up notifications again on each test device.
2. Create a follow-up due two minutes ahead.
3. Close the website tab.
4. Wait up to two minutes and confirm the system notification appears.
5. If it fails, inspect Lambda **Monitor** > **View CloudWatch logs**, then the
   EventBridge Scheduler execution history.

## Updating the backend later

After code changes, repeat the Docker build, tag, and push commands. In Lambda,
choose **Deploy new image**, select the latest ECR image, then deploy. Test the
Lambda URL before releasing the frontend.
