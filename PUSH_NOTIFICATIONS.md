# Follow-up push notifications

Settings → Follow-up notifications → Enable notifications registers this device for the current workspace. Enable each workspace separately. Only follow-ups created by the signed-in user are delivered. On iPhone, install the PWA and open it from the home screen before enabling notifications.

The backend checks pending follow-ups every 30 seconds on a continuously running server, and sends encrypted Web Push through the device's push provider. The service worker displays the notification when the app is closed. Tapping opens the full lead, with login required if necessary.

## Local setup

From the project directory:

```powershell
.\.venv\Scripts\python.exe -m pip install pywebpush==2.5.0
.\.venv\Scripts\python.exe scripts/setup-push.py
```

This saves `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` and `CRON_SECRET` to the ignored backend `.env`. Restart the backend. Keep the VAPID keys stable: changing them requires devices to re-enable notifications. The private key and cron secret must never go in the frontend environment.

## Deployment

Install backend requirements and set the four environment variables on the backend host using the values in your local backend `.env`. Set `VAPID_SUBJECT` to a contact email controlled by your organization. Deploy both frontend and backend.

On a persistent backend, leave `DISABLE_BACKGROUND_JOBS` off. On Vercel or another serverless backend, background loops are not reliable, so configure an external scheduler to call `POST /api/push/dispatch` every minute with `Authorization: Bearer <CRON_SECRET>`. GET is supported for platforms that only offer GET cron requests. Do not put the secret in the URL. Both methods require the same authorization. Serverless deployment alone does not schedule delivery.

Delivery records in MongoDB use atomic claims and leases to prevent concurrent workers from sending the same reminder to the same device. Transient errors retry after two minutes, up to five attempts. Expired subscriptions (404/410) are disabled. Rescheduled reminders use a new delivery key; done/cancelled reminders and unavailable leads are skipped. Pending reminders older than 24 hours are excluded to avoid a flood after downtime. Accepted push messages may still arrive after a last-second edit; network delivery is not an exactly-once guarantee.

Logging out disables the device's workspace subscriptions and unsubscribes it from the push provider. Foreground browser reminders are suppressed when server push is enabled for that device/workspace.

## Device test

1. Open the deployed installed app, sign in, and enable follow-up notifications in Settings.
2. Create a follow-up due two minutes from now, then close the app.
3. Confirm the alert arrives and tapping opens the correct lead.
4. Reschedule another reminder and complete/cancel one before it is due; confirm only pending due reminders alert.
5. Turn off notifications in Settings and confirm no more alerts for that workspace.

Phone permissions, Focus modes, battery settings, internet connectivity, and push-provider delays affect delivery timing. Validate on actual Android and iPhone devices before relying on notifications.

Implementation references: [Push API subscriptions](https://developer.mozilla.org/en-US/docs/Web/API/PushManager/subscribe), [pywebpush](https://github.com/web-push-libs/pywebpush).
