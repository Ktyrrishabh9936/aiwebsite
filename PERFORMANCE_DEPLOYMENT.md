# Performance deployment runbook

Deploy the backend to a preview environment before production. The backend
configuration enables Vercel Fluid Compute and selects `bom1` (Mumbai).
Confirm the Atlas primary is also in AWS `ap-south-1` before deploying this
configuration; if Atlas is elsewhere, co-locate Vercel with Atlas first rather
than introducing a cross-region database path.

## Backend deployment

1. Use the `backend` directory as the Vercel project root.
2. Configure the existing backend environment variables and Python 3.12.
3. Run the idempotent migration once against the preview database:

   ```powershell
   Set-Location backend
   python migrate_runtime.py
   ```

4. Deploy the backend, then the frontend. Existing API routes remain available
   while the frontend switches to the bootstrap endpoints.
5. Do not set `DISABLE_BACKGROUND_JOBS=1` until the qualification scheduler and
   Google Sheets renewal loops have an equivalent durable worker. The API logs
   a warning when these compatibility loops run on Vercel.

## Validation

Use a dedicated account and run at least 30 requests per endpoint:

```powershell
$env:PERF_BASE_URL='https://preview-backend.example/api'
$env:PERF_EMAIL='performance-account@example.com'
$env:PERF_PASSWORD='set-outside-source-control'
$env:PERF_RUNS='30'
python scripts/benchmark-api.py
```

Check Vercel runtime logs and each response's `Server-Timing` header. The target
is login p95 below 800 ms, ordinary API p95 below 500 ms, and CRM usable below
1.5 seconds. Repeat against production after rollout and retain the results for
comparison.
