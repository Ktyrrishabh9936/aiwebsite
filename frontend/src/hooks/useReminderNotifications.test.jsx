import React, { act } from "react";
import { createRoot } from "react-dom/client";
import api from "../lib/api";
import useReminderNotifications from "./useReminderNotifications";

jest.mock("../lib/api", () => ({ __esModule: true, default: { get: jest.fn() } }));

function Harness({ navigate }) {
  useReminderNotifications("ws", navigate);
  return null;
}

test("notifies once when a reminder becomes due and opens reminders on click", async () => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  const originalNotification = window.Notification;
  const notification = { close: jest.fn() };
  const MockNotification = jest.fn(() => notification);
  MockNotification.permission = "granted";
  Object.defineProperty(window, "Notification", { configurable: true, value: MockNotification });
  const focus = jest.spyOn(window, "focus").mockImplementation(() => {});
  const dueAt = new Date(Date.now() - 30000).toISOString();
  api.get.mockResolvedValue({ data: { items: [{ id: "reminder-1", title: "Call lead", lead_name: "Asha", scheduled_time: dueAt }], total: 1 } });
  const navigate = jest.fn();
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(<Harness navigate={navigate} />));
    expect(MockNotification).toHaveBeenCalledTimes(1);
    expect(MockNotification.mock.calls[0][0]).toBe("Reminder: Call lead");
    await act(async () => window.dispatchEvent(new Event("focus")));
    expect(MockNotification).toHaveBeenCalledTimes(1);
    notification.onclick();
    expect(navigate).toHaveBeenCalledWith("/app/w/ws/crm?tab=reminders");
  } finally {
    await act(async () => root.unmount());
    container.remove();
    focus.mockRestore();
    Object.defineProperty(window, "Notification", { configurable: true, value: originalNotification });
    jest.clearAllMocks();
  }
});
