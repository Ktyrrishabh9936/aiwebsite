# Minimal PWA test

Open `/pwa-test.html` on the frontend (for example `http://localhost:3000/pwa-test.html`). This is an isolated static test page; no React build or backend is needed for installation and offline testing. The existing frontend dev server serves it, and production builds copy it into `build/`.

For phone testing after deployment, open the HTTPS site and go to **Settings → Install on your phone → Open mobile app preview**. Settings includes separate Android Chrome and iPhone Safari installation steps. No ngrok change is needed.

1. Wait for **Offline setup: Ready**, then reload once.
2. Install using **Install test app** when enabled or the browser install menu. On iPhone, open in Safari and use **Share → Add to Home Screen**.
3. Launch the installed app. **App mode** should show **Installed app**.
4. Turn off the connection and reload. The small test page should still open.
5. Open the workspace offline: a reconnect page appears. Reconnect and select **Try again**.

Use localhost for desktop testing. Phone testing requires an HTTPS frontend URL; a plain HTTP LAN IP will not enable service workers. Installation UI depends on the browser and device.

This version caches only the test page, reconnect page, icons, and manifest. It does not cache account data, API responses, or the React application. Notifications and offline editing are outside this test.

In browser DevTools → Application, inspect Manifest and Service Workers. To remove the test, uninstall the app, unregister `service-worker.js`, and delete caches beginning with `arevei-pwa-test-`. Increase the cache version when changing cached test assets; updated workers activate after older controlled tabs close.
