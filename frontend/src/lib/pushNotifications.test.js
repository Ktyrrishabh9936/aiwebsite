import api from "./api";
import { enablePush, disablePush, removeDevicePush } from "./pushNotifications";

jest.mock("./api", () => ({ __esModule: true, default: { get: jest.fn(), put: jest.fn(), delete: jest.fn() } }));
let subscription, registration;
beforeEach(() => {
  jest.clearAllMocks();
  Object.defineProperty(window, "isSecureContext", { configurable: true, value: true });
  Object.defineProperty(window, "PushManager", { configurable: true, value: function () {} });
  Object.defineProperty(window, "Notification", { configurable: true, value: { requestPermission: jest.fn().mockResolvedValue("granted") } });
  subscription = { endpoint: "https://fcm.googleapis.com/test", toJSON: () => ({ endpoint: "https://fcm.googleapis.com/test", keys: {} }), unsubscribe: jest.fn().mockResolvedValue(true) };
  registration = { pushManager: { getSubscription: jest.fn().mockResolvedValue(null), subscribe: jest.fn().mockResolvedValue(subscription) } };
  Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: { register: jest.fn().mockResolvedValue(registration), ready: Promise.resolve(registration), getRegistration: jest.fn().mockResolvedValue(registration) } });
  api.get.mockResolvedValue({ data: { enabled: true, public_key: "AQID" } });
  api.put.mockResolvedValue({});
  api.delete.mockResolvedValue({});
});

test("permission is requested before async work and the subscription is saved for the workspace", async () => {
  const pending = enablePush("ws");
  expect(Notification.requestPermission).toHaveBeenCalledTimes(1);
  expect(api.get).not.toHaveBeenCalled();
  await pending;
  expect(registration.pushManager.subscribe).toHaveBeenCalledWith({ userVisibleOnly: true, applicationServerKey: new Uint8Array([1, 2, 3]) });
  expect(api.put).toHaveBeenCalledWith("/push/workspaces/ws/subscription", subscription.toJSON());
});

test("denied permission does not create a subscription", async () => {
  Notification.requestPermission.mockResolvedValue("denied");
  await expect(enablePush("ws")).rejects.toThrow("blocked");
  expect(api.put).not.toHaveBeenCalled();
});

test("disabling one workspace keeps the shared browser subscription", async () => {
  registration.pushManager.getSubscription.mockResolvedValue(subscription);
  await disablePush("ws");
  expect(api.delete).toHaveBeenCalledWith("/push/workspaces/ws/subscription", { data: { endpoint: subscription.endpoint } });
  expect(subscription.unsubscribe).not.toHaveBeenCalled();
});

test("logout unsubscribes the browser even when backend removal fails", async () => {
  registration.pushManager.getSubscription.mockResolvedValue(subscription);
  api.delete.mockRejectedValue(new Error("offline"));
  await expect(removeDevicePush()).rejects.toThrow("offline");
  expect(subscription.unsubscribe).toHaveBeenCalled();
});
