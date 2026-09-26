import api from "./api";

export function pushSupported() {
  return window.isSecureContext && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

function publicKeyBytes(key) {
  const padded = key + "=".repeat((4 - key.length % 4) % 4);
  return Uint8Array.from(atob(padded.replace(/-/g, "+").replace(/_/g, "/")), (char) => char.charCodeAt(0));
}

export async function currentDevice(wsId) {
  if (!pushSupported()) return { supported: false, enabled: false };
  const { data: config } = await api.get("/push/config");
  const registration = await navigator.serviceWorker.getRegistration(`${process.env.PUBLIC_URL || ""}/`);
  const subscription = await registration?.pushManager.getSubscription();
  if (!subscription) return { supported: true, configured: config.enabled, enabled: false };
  const { data } = await api.get(`/push/workspaces/${wsId}/subscription`, { params: { endpoint: subscription.endpoint } });
  return { supported: true, configured: config.enabled, enabled: data.enabled, subscription };
}

export async function enablePush(wsId) {
  if (!pushSupported()) throw new Error("Open the installed app or use a browser that supports notifications over HTTPS.");
  // Invoke permission directly from the button's user gesture (required on iPhone).
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Notifications are blocked. Allow them in your browser or phone settings, then try again.");
  const { data: config } = await api.get("/push/config");
  if (!config.enabled) throw new Error("Notifications are not configured on the server yet.");
  await navigator.serviceWorker.register(`${process.env.PUBLIC_URL || ""}/service-worker.js`, { updateViaCache: "none" });
  const registration = await navigator.serviceWorker.ready;
  let subscription = await registration.pushManager.getSubscription();
  const key = publicKeyBytes(config.public_key);
  if (subscription?.options.applicationServerKey &&
      Array.from(new Uint8Array(subscription.options.applicationServerKey)).join() !== Array.from(key).join()) {
    await subscription.unsubscribe();
    subscription = null;
  }
  if (!subscription) subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
  await api.put(`/push/workspaces/${wsId}/subscription`, subscription.toJSON());
  window.dispatchEvent(new Event("arevei:push-changed"));
}

export async function disablePush(wsId) {
  const registration = await navigator.serviceWorker.getRegistration(`${process.env.PUBLIC_URL || ""}/`);
  const subscription = await registration?.pushManager.getSubscription();
  if (subscription) await api.delete(`/push/workspaces/${wsId}/subscription`, { data: { endpoint: subscription.endpoint } });
  window.dispatchEvent(new Event("arevei:push-changed"));
}

export async function removeDevicePush() {
  if (!("serviceWorker" in navigator)) return;
  const registration = await navigator.serviceWorker.getRegistration(`${process.env.PUBLIC_URL || ""}/`);
  const subscription = await registration?.pushManager.getSubscription();
  if (subscription) {
    try { await api.delete("/push/device", { data: { endpoint: subscription.endpoint } }); }
    finally { await subscription.unsubscribe(); }
  }
}
