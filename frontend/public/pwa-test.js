const installButton = document.getElementById("install");
const appMode = window.matchMedia("(display-mode: standalone)");
let installPrompt;

function updateStatus() {
  document.getElementById("connection").textContent = navigator.onLine ? "Online" : "Offline";
  const installed = appMode.matches || navigator.standalone === true;
  document.getElementById("mode").textContent = installed ? "Installed app" : "Browser";
  if (installed) {
    installButton.textContent = "App installed";
    installButton.disabled = true;
  }
}
window.addEventListener("online", updateStatus);
window.addEventListener("offline", updateStatus);
appMode.addEventListener("change", updateStatus);
window.addEventListener("appinstalled", () => { installPrompt = null; updateStatus(); });
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  installPrompt = event;
  installButton.disabled = false;
});
installButton.addEventListener("click", async () => {
  if (!installPrompt) return;
  try {
    await installPrompt.prompt();
    await installPrompt.userChoice;
  } finally {
    installPrompt = null;
    installButton.disabled = true;
  }
});
updateStatus();

async function setupOffline() {
  const status = document.getElementById("worker");
  if (!("serviceWorker" in navigator) || !window.isSecureContext) {
    status.textContent = "Requires HTTPS or localhost";
    return;
  }
  try {
    await navigator.serviceWorker.register("./service-worker.js", { updateViaCache: "none" });
    await navigator.serviceWorker.ready;
    status.textContent = "Ready";
  } catch (error) {
    status.textContent = "Setup failed — reload to retry";
    console.error("PWA test setup failed", error);
  }
}
setupOffline();
