// Same-origin requests use the backend's session cookie.
export async function api(path, { method = "GET", body, signal } = {}) {
  const response = await fetch("/api/v1" + path, {
    method, signal, credentials: "same-origin", cache: "no-store",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = response.status === 204 ? null : await response.json().catch(() => ({ detail: "Server unavailable." }));
  if (!response.ok) {
    const message = typeof data?.detail === "string" ? data.detail : "Request failed.";
    throw Object.assign(new Error(message), { status: response.status });
  }
  return data;
}

export const escape = (value) => String(value ?? "").replace(/[&<>"']/g,
  (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
export const id = encodeURIComponent;
export const date = (value) => value ? new Date(value).toLocaleString() : "—";
export const button = (label, action, value = "", style = "secondary") =>
  `<button type="button" class="btn btn-${style}" data-action="${action}" data-value="${escape(value)}">${label}</button>`;
export const tag = (status, success = false) =>
  `<span class="tag ${success || status === "passed" ? "tag-success" : status === "failed" || status === "timeout" ? "tag-danger" : ""}">${escape(success ? "validated" : status)}</span>`;
export const heading = (label, title, description = "") =>
  `<div class="view-header"><p class="card-system-tag">${escape(label)}</p><h1>${escape(title)}</h1><p class="text-muted">${escape(description)}</p></div>`;
export const card = (title, content) =>
  `<section class="card"><h2 class="card-tab">${escape(title)}</h2>${content}</section>`;
export const field = (label, name, type = "text", extra = "") =>
  `<label class="form-group">${label}<input name="${name}" type="${type}" required ${extra}></label>`;
export const download = (url, name) =>
  `<a class="btn btn-secondary" href="${escape(url)}" download>${escape(name)}</a>`;
export const pager = (data, href) => `<div class="pagination">
  <a ${data.offset ? `href="${escape(href(Math.max(0, data.offset - data.limit)))}"` : 'aria-disabled="true"'}>← Previous</a>
  <span>${data.total ? data.offset + 1 : 0}–${Math.min(data.offset + data.limit, data.total)} / ${data.total}</span>
  <a ${data.offset + data.limit < data.total ? `href="${escape(href(data.offset + data.limit))}"` : 'aria-disabled="true"'}>Next →</a></div>`;
