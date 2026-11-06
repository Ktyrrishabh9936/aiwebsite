import { useEffect, useReducer } from "react";

// Chrome fires `beforeinstallprompt` once, shortly after the page loads. Capture it at
// startup so an install button rendered later (after sign-in) can still open the native
// install dialog immediately.
let deferredPrompt = null;
let capturing = false;
let workerRequested = false;
const listeners = new Set();

function notify() {
  listeners.forEach((listener) => listener());
}

export function captureInstallPrompt() {
  if (capturing || typeof window === "undefined") return;
  capturing = true;
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event;
    notify();
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    notify();
  });
}

export function isInstalledApp() {
  if (typeof window === "undefined") return false;
  if (window.Capacitor?.isNativePlatform?.()) return true;
  if (navigator.standalone === true) return true;
  return typeof window.matchMedia === "function" && window.matchMedia("(display-mode: standalone)").matches;
}

export function isIosDevice() {
  const agent = navigator.userAgent || "";
  return /iPhone|iPad|iPod/.test(agent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

export function installInstructions() {
  if (isIosDevice()) return "In Safari, tap Share, then Add to Home Screen, then Add.";
  return "Open your browser menu and choose Install app or Add to Home screen. If neither is listed, this browser can't install apps.";
}

// Opens the browser's install dialog. Resolves to "accepted", "dismissed", or "unavailable".
export async function promptInstall() {
  const event = deferredPrompt;
  if (!event) return "unavailable";
  // A dismissed prompt can't be reused; the browser offers a new event on the next load.
  deferredPrompt = null;
  notify();
  try {
    await event.prompt();
    const choice = await event.userChoice;
    return choice?.outcome === "accepted" ? "accepted" : "dismissed";
  } catch {
    return "unavailable";
  }
}

// Some Android browsers only offer installation once a service worker controls the page.
function ensureServiceWorker() {
  if (workerRequested || typeof window === "undefined" || !window.isSecureContext || !("serviceWorker" in navigator)) return;
  workerRequested = true;
  navigator.serviceWorker.register(`${process.env.PUBLIC_URL || ""}/service-worker.js`, { updateViaCache: "none" }).catch((error) => {
    console.error("Install setup failed", error);
  });
}

export function useInstallApp() {
  const [, rerender] = useReducer((count) => count + 1, 0);
  useEffect(() => {
    captureInstallPrompt();
    ensureServiceWorker();
    listeners.add(rerender);
    const media = typeof window.matchMedia === "function" ? window.matchMedia("(display-mode: standalone)") : null;
    media?.addEventListener?.("change", rerender);
    return () => {
      listeners.delete(rerender);
      media?.removeEventListener?.("change", rerender);
    };
  }, []);
  return { installed: isInstalledApp(), canPrompt: Boolean(deferredPrompt), promptInstall, instructions: installInstructions() };
}
