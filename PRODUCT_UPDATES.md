# Publishing product updates

Before shipping a user-visible change, add a release to `frontend/src/lib/productUpdates.js`. Keep existing release IDs stable and put the newest release first. Include a date, plain-language title, feature descriptions, workspace-relative destinations and selectors for updated controls. Use stable `data-update` attributes for tabs and feature buttons.

The shipped release list powers the workspace header's New updates button. New release IDs produce an unread indicator, a one-time toast and feature highlights. Explore links open the feature in the current workspace. Mark all as read clears highlights without removing release history.

Seen release IDs are stored separately per signed-in user in browser localStorage; another browser or device can show them as unread. This feature does not send email or push notifications. Publish the frontend build with the release entry to announce it; code edits alone are not a deployment.

Validate release links, highlights, acknowledgement and the production build before publishing.
