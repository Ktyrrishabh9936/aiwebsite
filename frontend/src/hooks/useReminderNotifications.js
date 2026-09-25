import { useEffect } from "react";
import api from "../lib/api";

export default function useReminderNotifications(wsId, navigate) {
  useEffect(() => {
    if (!wsId || typeof window === "undefined" || typeof Notification === "undefined") return undefined;
    let active = true;
    let checking = false;
    let lastChecked = Date.now() - 2 * 60 * 1000;
    const storageKey = `arevei_reminder_notifications_${wsId}`;

    const checkDue = async () => {
      if (!active || checking || Notification.permission !== "granted") return;
      checking = true;
      const checkedAt = Date.now();
      try {
        const notified = JSON.parse(localStorage.getItem(storageKey) || "{}");
        const start = new Date(lastChecked - 30 * 1000).toISOString();
        const end = new Date(checkedAt).toISOString();
        let offset = 0;
        let total = 0;
        do {
          const response = await api.get(`/workspaces/${wsId}/crm/reminders`, {
            params: { status: "pending", start, end, offset, limit: 100 },
          });
          if (!active) return;
          const items = response.data.items || [];
          total = response.data.total || 0;
          for (const item of items) {
            if (notified[item.id] === item.scheduled_time) continue;
            const dueAt = new Date(item.scheduled_time);
            if (Number.isNaN(dueAt.getTime()) || dueAt.getTime() > checkedAt) continue;
            const notification = new Notification(`Reminder: ${item.title}`, {
              body: `${item.lead_name || "Lead"} · Due ${dueAt.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`,
              tag: `crm-reminder-${wsId}-${item.id}`,
            });
            notification.onclick = () => { window.focus(); navigate(`/app/w/${wsId}/crm?tab=reminders`); notification.close(); };
            notified[item.id] = item.scheduled_time;
            localStorage.setItem(storageKey, JSON.stringify(notified));
          }
          offset += items.length;
          if (!items.length) break;
        } while (offset < total);
        lastChecked = checkedAt;
      } catch {
        // Keep the prior check time so a temporary API or browser failure can be retried.
      } finally {
        checking = false;
      }
    };

    const enabled = () => { lastChecked = Date.now() - 2 * 60 * 1000; checkDue(); };
    const timer = window.setInterval(checkDue, 30000);
    window.addEventListener("focus", checkDue);
    window.addEventListener("arevei:reminder-notifications-enabled", enabled);
    checkDue();
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", checkDue);
      window.removeEventListener("arevei:reminder-notifications-enabled", enabled);
    };
  }, [wsId, navigate]);
}
