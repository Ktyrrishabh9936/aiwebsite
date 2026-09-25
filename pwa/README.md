# CRM mobile PWA

This folder is reserved for the installable mobile CRM. It is separate from
`frontend/`, so the existing desktop site keeps its current entry point and
build process.

## Planned boundary

- The PWA will have its own app shell, manifest, icons, service worker, and
  build configuration in this folder.
- It will use the existing backend accounts, workspaces, CRM leads, and
  reminders through the authenticated `/api` endpoints.
- Its service worker will be scoped only to the PWA URL path. It must not cache
  authenticated API responses or take control of the desktop site.
- Mobile reminder alerts while the app is closed require Web Push subscriptions
  and a backend sender. The current desktop reminder polling works only while
  the workspace page is open.

## Deployment decision

Choose a permanent HTTPS path or subdomain for this app before enabling its
service worker and push subscriptions. Configure that origin in backend CORS
if it differs from the existing frontend origin. The PWA needs an API base URL
that is reachable from a phone; `localhost` and a temporary ngrok URL cannot
serve as its production API address.

No PWA code is deployed from this folder yet.
