import { getAppTimezone } from "./timezone";
import api, { API } from "./api";

export function newManagerId() {
  return crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function managerConversationKey(wsId) {
  // Scope browser memory to the signed-in user as well as the workspace.
  let user = "session";
  try {
    const token = localStorage.getItem("arevei_token") || "";
    const payload = token.split(".")[1];
    if (payload) user = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/"))).sub || user;
  } catch { /* Backend remains the authority for identity. */ }
  return `arevei_manager_conversation_${user}_${wsId}`;
}

export function conversationId(wsId) {
  const key = managerConversationKey(wsId);
  let id = localStorage.getItem(key);
  if (!id) { id = newManagerId(); localStorage.setItem(key, id); }
  return id;
}

export async function loadManagerConversation(wsId, id) {
  return (await api.get(`/workspaces/${wsId}/manager/conversation/${id}`)).data;
}

export async function getManagerRun(wsId, id) {
  return (await api.get(`/workspaces/${wsId}/manager/runs/${id}`)).data;
}

export async function streamManagerAgent(wsId, message, options, onText) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 330000);
  let reader, answer = "", finished = false, buffer = "";
  const receive = (event) => {
    options.onEvent?.(event);
    if (event.type === "answer") { answer = event.content; onText(answer); }
    if (event.type === "tool_finished" && event.writes && event.status === "completed")
      window.dispatchEvent(new Event("arevei:manager-changed"));
    if (event.type === "run_finished") {
      finished = true;
      if (event.status !== "completed") {
        const error = new Error(event.label || "Manager run stopped");
        error.managerMessage = true;
        throw error;
      }
    }
  };
  try {
    const response = await fetch(`${API}/workspaces/${wsId}/manager/runs`, {
      method: "POST", signal: controller.signal,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.getItem("arevei_token")}` },
      body: JSON.stringify({ message, conversation_id: options.conversationId,
        request_id: options.requestId, timezone: getAppTimezone() }),
    });
    if (!response.ok) {
      const failure = await response.json().catch(() => ({}));
      const error = new Error(typeof failure.detail === "string" ? failure.detail : `HTTP ${response.status}`);
      error.managerMessage = typeof failure.detail === "string";
      throw error;
    }
    if (response.headers.get("content-type")?.includes("application/json")) {
      const replay = await response.json();
      const run = await getManagerRun(wsId, replay.run_id);
      for (const event of run.events || []) receive(event);
      if (run.status === "running") throw new Error("This request is still running. Its activity is saved; check the work panel.");
    } else {
      reader = response.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        let split;
        while ((split = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, split);
          buffer = buffer.slice(split + 2);
          const data = frame.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
          if (data) receive(JSON.parse(data));
        }
        if (done) break;
      }
    }
    if (!finished) throw new Error("Connection ended before completion. Check saved activity before retrying.");
    return answer;
  } catch (error) {
    if (controller.signal.aborted) throw new Error("Manager request timed out; completed changes remain saved.");
    throw error;
  } finally {
    clearTimeout(timer);
    if (reader) { reader.cancel().catch(() => {}); reader.releaseLock(); }
  }
}
