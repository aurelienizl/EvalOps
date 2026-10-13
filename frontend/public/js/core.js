/** Shared API, session state, DOM helpers and environment polling. */
export const $ = id => document.getElementById(id);
export const state = {
  user: null, csrfToken: null, environment: null, isLocked: false,
  operationPending: false, activeExerciseId: null, exerciseAvailable: false,
  pollTimer: null, routeVersion: 0, sessionVersion: 0,
};

let pollRequest = null;

export async function apiCall(endpoint, options = {}) {
  const version = state.sessionVersion;
  const headers = new Headers(options.headers);
  const method = (options.method || "GET").toUpperCase();
  let body = options.body;
  if (state.csrfToken && ["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    headers.set("X-CSRF-Token", state.csrfToken);
  }
  if (body && Object.getPrototypeOf(body) === Object.prototype) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(body);
  }

  const response = await fetch(endpoint, { ...options, method, headers, body, credentials: "same-origin" });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const details = data?.error || { code: "SERVER_ERROR", message: `Request failed (${response.status})` };
    if (details.code === "AUTHENTICATION_REQUIRED" && state.user && version === state.sessionVersion) clearSession();
    throw Object.assign(new Error(details.message), { code: details.code, status: response.status, details });
  }
  if (!data || typeof data !== "object") throw new Error("The server returned an invalid response");
  return data;
}

export function cloneTemplate(id) {
  return $(id).content.firstElementChild.cloneNode(true);
}

export function showMessage(container, text, className = "text-muted mono loading-message") {
  const message = document.createElement(className.includes("alert") ? "div" : "p");
  message.className = className;
  message.textContent = text;
  container.replaceChildren(message);
}

export function showToast(message, duration = 3000) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  $("toast-container").appendChild(toast);
  setTimeout(() => toast.remove(), duration);
}

export function formatDate(iso) {
  if (!iso) return "-";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString("en-US", {
    month: "short", day: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
  });
}

function notifyEnvironment() {
  state.isLocked = state.operationPending || !!state.environment?.locked;
  document.dispatchEvent(new CustomEvent("environmentchange"));
}

export function setOperationPending(pending) {
  state.operationPending = pending;
  notifyEnvironment();
}

export function setSession(user, csrfToken) {
  clearTimeout(state.pollTimer);
  state.sessionVersion++;
  pollRequest = null;
  state.pollTimer = null;
  state.user = user;
  state.csrfToken = csrfToken;
  document.dispatchEvent(new CustomEvent("sessionchange"));
}

export function clearSession() {
  setSession(null, null);
  state.environment = null;
  state.operationPending = false;
  state.activeExerciseId = null;
  state.exerciseAvailable = false;
  notifyEnvironment();
}

export async function pollEnvironment(force = false) {
  if (!state.user) return;
  const version = state.sessionVersion;
  if (pollRequest) {
    if (!force) return pollRequest;
    await pollRequest;
    if (version !== state.sessionVersion || !state.user) return;
    return pollEnvironment();
  }
  clearTimeout(state.pollTimer);
  state.pollTimer = null;
  const request = (async () => {
    try {
      const environment = await apiCall("/api/v1/environment");
      if (version !== state.sessionVersion) return;
      state.environment = environment;
      notifyEnvironment();
    } catch (error) {
      if (version === state.sessionVersion) console.warn("Poll environment error:", error);
    } finally {
      if (pollRequest === request) pollRequest = null;
      if (version === state.sessionVersion && state.user) {
        const interval = state.isLocked ? 2000 : state.environment?.state === "running" ? 10000 : 30000;
        state.pollTimer = setTimeout(pollEnvironment, interval);
      }
    }
  })();
  pollRequest = request;
  return request;
}
