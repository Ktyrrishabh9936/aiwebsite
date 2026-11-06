import { captureInstallPrompt, isInstalledApp, promptInstall } from "./installApp";

function installEvent(outcome) {
  const event = new Event("beforeinstallprompt", { cancelable: true });
  event.prompt = jest.fn().mockResolvedValue(undefined);
  event.userChoice = Promise.resolve({ outcome });
  return event;
}

beforeEach(() => {
  captureInstallPrompt();
  window.dispatchEvent(new Event("appinstalled"));
});

test("reports unavailable when the browser never offered an install prompt", async () => {
  expect(await promptInstall()).toBe("unavailable");
});

test("captures the browser prompt and opens it on demand only once", async () => {
  const event = installEvent("accepted");
  window.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(true);
  expect(await promptInstall()).toBe("accepted");
  expect(event.prompt).toHaveBeenCalledTimes(1);
  expect(await promptInstall()).toBe("unavailable");
});

test("reports a dismissed prompt", async () => {
  window.dispatchEvent(installEvent("dismissed"));
  expect(await promptInstall()).toBe("dismissed");
});

test("detects the installed app on iPhone and inside the native shell", () => {
  expect(isInstalledApp()).toBe(false);
  Object.defineProperty(navigator, "standalone", { configurable: true, value: true });
  expect(isInstalledApp()).toBe(true);
  Object.defineProperty(navigator, "standalone", { configurable: true, value: undefined });
  window.Capacitor = { isNativePlatform: () => true };
  expect(isInstalledApp()).toBe(true);
  delete window.Capacitor;
});
