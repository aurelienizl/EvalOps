import assert from "node:assert/strict";
import test from "node:test";

import { escapeHtml } from "../../frontend/public/js/html.js";
import { renderSafeMarkdown } from "../../frontend/public/js/markdown.js";
import { apiCall, state } from "../../frontend/public/js/core.js";
import { updateButtonsLockState } from "../../frontend/public/js/components/environment-banner.js";

test("HTML and Markdown keep injected markup inert", () => {
  const payload = '<img src=x onerror="alert(1)"> & \'quoted\'';
  assert.equal(escapeHtml(payload), "&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; &#039;quoted&#039;");
  assert.equal(renderSafeMarkdown(payload), `<p>${escapeHtml(payload)}</p>`);
  assert.equal(renderSafeMarkdown("```html\n<script>alert(1)</script>\n```"),
    '<pre><code class="language-html">&lt;script&gt;alert(1)&lt;/script&gt;</code></pre>');
});

test("mutations send JSON and the current CSRF token", async t => {
  const previousToken = state.csrfToken;
  t.after(() => { state.csrfToken = previousToken; });
  state.csrfToken = "csrf-token";
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/api/v1/environment/stop");
    assert.equal(options.method, "POST");
    assert.equal(options.credentials, "same-origin");
    assert.equal(options.headers.get("X-CSRF-Token"), "csrf-token");
    assert.equal(options.headers.get("Content-Type"), "application/json");
    assert.equal(options.body, '{"reason":"user"}');
    return new Response(null, { status: 204 });
  });
  assert.equal(await apiCall("/api/v1/environment/stop", { method: "post", body: { reason: "user" } }), null);
});

test("proxy errors and malformed successful responses are reported", async t => {
  const fetchMock = t.mock.method(globalThis, "fetch", async () => new Response("Bad gateway", { status: 502 }));
  await assert.rejects(apiCall("/api/v1/courses"), error => error.status === 502 && error.message === "Request failed (502)");
  fetchMock.mock.mockImplementation(async () => new Response("<html>Unexpected response</html>"));
  await assert.rejects(apiCall("/api/v1/courses"), /invalid response/);
});

test("an expired request cannot clear a newer session", async t => {
  const previousUser = state.user;
  const previousVersion = state.sessionVersion;
  t.after(() => { state.user = previousUser; state.sessionVersion = previousVersion; });
  let resolve;
  t.mock.method(globalThis, "fetch", () => new Promise(done => { resolve = done; }));
  state.user = { id: "old-user" };
  const request = apiCall("/api/v1/environment");
  state.user = { id: "new-user" };
  state.sessionVersion++;
  resolve(Response.json({ error: { code: "AUTHENTICATION_REQUIRED", message: "Expired" } }, { status: 401 }));
  await assert.rejects(request, /Expired/);
  assert.equal(state.user.id, "new-user");
});

test("unavailable exercises and active operations disable environment actions", t => {
  const previousState = { ...state };
  const previousDocument = globalThis.document;
  t.after(() => {
    Object.assign(state, previousState);
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  });
  const elements = Object.fromEntries(["btn-start", "btn-grade", "btn-stop", "btn-save-ssh-key", "banner-btn-stop", "operation-notice"]
    .map(id => [id, { dataset: {}, disabled: false, classList: { toggle() {} } }]));
  globalThis.document = { getElementById: id => elements[id] };
  Object.assign(state, { user: { id: "student", role: "student" }, isLocked: false, activeExerciseId: "exercise", exerciseAvailable: false, environment: { state: "stopped" } });
  updateButtonsLockState();
  assert.equal(elements["btn-start"].disabled, true);
  assert.equal(elements["btn-grade"].disabled, true);
  assert.equal(elements["btn-stop"].disabled, true);
  assert.equal(elements["btn-save-ssh-key"].disabled, false);

  state.exerciseAvailable = true;
  state.environment = { state: "running" };
  updateButtonsLockState();
  assert.equal(elements["btn-start"].disabled, false);
  assert.equal(elements["btn-stop"].disabled, false);
  state.user = { id: "admin", role: "admin" };
  updateButtonsLockState();
  assert.equal(elements["btn-start"].disabled, true);
  assert.equal(elements["btn-grade"].disabled, true);
  assert.equal(elements["btn-stop"].disabled, true);
  state.user = { id: "student", role: "student" };
  state.isLocked = true;
  updateButtonsLockState();
  for (const id of ["btn-start", "btn-grade", "btn-stop", "banner-btn-stop"]) assert.equal(elements[id].disabled, true);
});

test("interrupted evaluations display their error instead of a null score", async t => {
  const previousDocument = globalThis.document;
  t.after(() => {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  });
  const fields = { "[data-error-code]": {}, "[data-error-message]": {} };
  const errorCard = { querySelector: selector => fields[selector] };
  const body = { children: [], replaceChildren() { this.children = []; }, append(card) { this.children.push(card); } };
  const elements = {
    "modal-eval": { classList: { contains: () => false, remove() {} } },
    "modal-eval-body": body,
    "modal-eval-title": {},
    "template-evaluation-error": { content: { firstElementChild: { cloneNode: () => errorCard } } },
  };
  globalThis.document = { getElementById: id => elements[id] };
  const { showEvaluationModal } = await import("../../frontend/public/js/pages/exercise.js");
  showEvaluationModal({ status: "interrupted", error_code: "EVALUATION_INTERRUPTED", error_message: "Manager restarted" });
  assert.equal(body.children[0], errorCard);
  assert.equal(fields["[data-error-code]"].textContent, "EVALUATION_INTERRUPTED");
  assert.equal(fields["[data-error-message]"].textContent, "Manager restarted");
});
