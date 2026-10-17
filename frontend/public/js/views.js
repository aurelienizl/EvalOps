import { escape as e, id, date, button, tag, heading, card, field, download, pager } from "./api.js";
import { marked } from "../vendor/marked.js";
const { DOMPurify } = window;

const empty = (text) => `<p class="empty-message">${text}</p>`;
const difficulties = { warmup: "WARM-UP // GETTING STARTED", easy: "LEVEL // EASY", medium: "LEVEL // MEDIUM", hard: "LEVEL // HARD" };
const auditLink = (key, value, label) => `<a href="#admin/evaluations?${e(new URLSearchParams({ [key]: value }))}" title="${e(value)}">${e(label)}</a>`;
function duration(milliseconds) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000)), minutes = Math.floor(seconds / 60);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : minutes ? `${minutes}m ${seconds % 60}s` : `${seconds}s`;
}
const evaluationTime = (data) => data.created_at ? duration(new Date(data.finished_at || Date.now()) - new Date(data.created_at)) : "—";

export function login() {
  return `<section class="auth-card">${heading("EVALOPS // CONSOLE LOGIN", "Authentication", "Access your DevOps workspace console and training labs.")}
    <form data-form="login">${field("Email address", "email", "email", 'autocomplete="email" maxlength="255"')}
    ${field("Password", "password", "password", 'autocomplete="current-password" maxlength="1024"')}
    <button class="btn btn-primary btn-block">Sign in</button></form></section>`;
}

export function courses(data) {
  return heading("CATALOG // CURRICULUM", "DevOps Modules", "Select a module to start or continue your practical coursework.") +
    `<div class="courses-grid">${data.items.map((c) => `<a class="card course-card" href="#courses/${id(c.id)}">
      <p class="card-system-tag">MODULE // ${e(c.id)}</p><div class="course-card-header"><h2>${e(c.name)}</h2>
      ${tag("pending", c.total_exercises > 0 && c.completed_exercises === c.total_exercises)}</div>
      <p class="mono text-muted">DEADLINE // ${e(date(c.deadline))}</p>
      <progress max="${Math.max(1, c.total_exercises)}" value="${c.completed_exercises}" aria-label="Completion"></progress>
      <div class="course-card-stats"><span>VALIDATED <strong>${c.completed_exercises} / ${c.total_exercises}</strong></span><span>OPEN →</span></div>
    </a>`).join("")}</div>` + (!data.items.length ? empty("No modules available yet.") : "");
}

export function course(data) {
  return `<a class="breadcrumb" href="#courses">← BACK TO MODULES</a>` +
    heading("MODULE SPECIFICATION", data.name, "DEADLINE // " + date(data.deadline)) +
    Object.entries(difficulties).map(([level, title]) => {
      const exercises = data.exercises.filter((x) => x.difficulty === level);
      return exercises.length ? `<details class="difficulty-section" open><summary class="difficulty-title">${title}
        <span>${exercises.length} exercises</span></summary><div class="exercises-grid">
        ${exercises.map((x) => `<a class="exercise-tile ${x.is_completed ? "completed" : ""}" href="#exercises/${id(x.id)}">
          <p class="card-system-tag">${e(x.id)}</p><h2>${e(x.name)}</h2><div class="exercise-tile-footer">
          ${tag("pending", x.is_completed)}<span>OPEN →</span></div></a>`).join("")}</div></details>` : "";
    }).join("") + (!data.exercises.length ? empty("No exercises available yet.") : "");
}

export function exercise(data) {
  const subject = DOMPurify.sanitize(marked.parse(data.subject || ""), {
    USE_PROFILES: { html: true }, FORBID_TAGS: ["img", "form", "input", "button", "style"],
  });
  return `<a class="breadcrumb" href="#courses/${id(data.course_id)}">← BACK TO MODULE</a>
    <div class="exercise-header"><div>${heading("EXERCISE SPECIFICATION", data.name)}<div id="exercise-meta" class="exercise-tags"></div></div>
    <div class="button-row">${button("▶ Start environment", "start", data.id, "primary")}
    ${button("✓ Evaluate", "grade", data.id, "success")}${button("■ Stop", "stop", "", "danger")}</div></div>
    <p id="operation-notice" class="alert" hidden></p><div class="exercise-layout">
    ${card("README.md // SPECIFICATIONS", `<article class="markdown-body">${subject}</article>`)}
    <aside class="exercise-sidebar">${card("RESOURCES // ATTACHMENTS", `<div class="resources-list">${data.resources.map((r) =>
      download(r.download_url, "↓ " + r.name)).join("") || empty("No attachments.")}</div>`)}
    ${card("HISTORY // AUDIT TRAIL", '<div id="history">Loading evaluations…</div>')}</aside></div>`;
}

export function history(data, exerciseId) {
  return `<div class="history-list">${data.items.map((x) => `<button type="button" class="history-item" data-action="report" data-value="${e(x.id)}">
    <span class="history-summary">${tag(x.status, x.is_success)}<time>${e(date(x.created_at))}</time></span>
    <span>${x.passed_tests ?? 0} / ${x.total_tests ?? 0} tests passed</span></button>`).join("") || empty("No evaluations yet.")}</div>` +
    pager(data, (offset) => `#exercises/${id(exerciseId)}?offset=${offset}`);
}

export function profile(user) {
  return heading("SECURITY // IDENTITY", "Profile & Settings", "Configure your public SSH access key and manage your account credentials.") +
    `<div class="identity-strip"><strong>${e(user.email)}</strong>${tag(user.role)}<code>${e(user.id)}</code></div>
    <div class="profile-cards">${card("SSH CREDENTIALS // AUTHORIZED_KEYS", `<h2>Public SSH key</h2>
      <p id="key-status" class="card-subtitle"></p><p class="card-subtitle">Use an Ed25519 or RSA public key (RSA: at least 3072 bits).</p>
      <form data-form="key"><label class="form-group">Public SSH key<textarea name="public_key" rows="4" maxlength="8192" required spellcheck="false" placeholder="ssh-ed25519 AAAAC3…"></textarea></label>
      <button class="btn btn-primary">Save SSH key</button></form>`)}
    ${card("AUTHENTICATION // PASSWORD", `<h2>Change password</h2><p class="card-subtitle">Changing your password signs you out of every session.</p>
      <form data-form="password">${field("Current password", "current_password", "password", 'autocomplete="current-password" maxlength="1024"')}
      ${field("New password (at least 12 characters)", "new_password", "password", 'autocomplete="new-password" minlength="12" maxlength="1024"')}
      ${field("Confirm new password", "confirm", "password", 'autocomplete="new-password" minlength="12" maxlength="1024"')}
      <button class="btn btn-secondary">Update password</button></form>`)}</div>`;
}

export function report(data) {
  return `<div class="report-summary">${tag(data.status, data.is_success)}<code>${e(data.id)}</code>
    <p>${e(data.email)} ${e(data.exercise_id)} · ${e(date(data.created_at))}</p>
    ${data.user_id ? `<p>Student ID: <code>${e(data.user_id)}</code></p>` : ""}
    <p>Finished: ${e(date(data.finished_at))} · Elapsed since submission: ${evaluationTime(data)}</p></div>
    ${data.status === "running" && !data.finished_at ? '<p class="alert">Evaluation in progress. Environment controls remain locked until cleanup finishes.</p>' : ""}
    ${data.error_message ? `<p class="alert alert-error">${e(data.error_message)}</p>` : ""}
    ${data.error_code ? `<p class="mono">${e(data.error_code)}</p>` : ""}
    ${data.total_tests != null ? `<h3 class="report-score">${data.passed_tests ?? 0} / ${data.total_tests} TESTS PASSED</h3>` : ""}
    ${data.snapshot_available ? download(`/api/v1/evaluations/${id(data.id)}/snapshot`, "↓ Download submitted workspace") : ""}
    <div class="report-tests">${(data.tests || []).map((t) => `<details class="test-result ${e(t.status)}" ${t.status !== "passed" ? "open" : ""}>
      <summary><span>${e(t.name)}</span>${tag(t.status)}</summary><p>Exit code: ${e(t.return_code ?? "—")} · ${e(t.execution_time_ms ?? "—")} ms</p>
      ${t.stdout_diff ? `<h4>Output</h4><pre class="diff">${e(t.stdout_diff)}</pre>` : ""}
      ${t.stderr_diff ? `<h4>Diagnostics</h4><pre class="diff">${e(t.stderr_diff)}</pre>` : ""}</details>`).join("")}</div>`;
}

export function admin(tab, query) {
  return `<div class="admin-header">${heading("ADMINISTRATION // CONTROL PANEL", "Platform Administration", "Monitor development environments and audit evaluations.")}
    ${button("Refresh", "refresh")}</div><nav class="admin-tabs" aria-label="Administration sections">
    ${[["overview", "Overview & Metrics"], ["environments", "Active Operations"], ["evaluations", "Audit Logs"]].map(([key, label]) =>
      `<a class="admin-tab" href="#admin/${key}" ${tab === key ? 'aria-current="page"' : ""}>${label}</a>`).join("")}</nav>
    <div id="admin-stats" class="admin-stats-grid"></div>
    ${tab === "evaluations" ? `<form class="admin-filters" data-form="filters">
      <label>Student ID<input name="user_id" value="${e(query.get("user_id"))}" placeholder="Student UUID"></label>
      <label>Exercise<input name="exercise_id" value="${e(query.get("exercise_id"))}" placeholder="Exercise ID"></label>
      <label>Status<select name="status">${["", "running", "completed", "failed", "timeout"].map((s) =>
        `<option value="${s}" ${s === query.get("status") ? "selected" : ""}>${s || "All statuses"}</option>`).join("")}</select></label>
      <button class="btn btn-secondary">Apply filters</button></form>` : ""}
    <div id="admin-panel">Loading operations…</div>`;
}

export function adminStats(data) {
  const finished = data.evaluations - data.pending_evaluations;
  return [["USERS", data.users, "Total accounts"], ["EVALUATIONS", data.evaluations, "Total submissions"],
    ["RUNTIMES", data.active_environments, "Active environments and operations"],
    ["PENDING", auditLink("status", "running", data.pending_evaluations), "Queued or grading · view logs"],
    ["PASSED", data.successful_evaluations, "Successful evaluations"],
    ["SUCCESS RATE", finished > 0 ? `${Math.round(data.successful_evaluations / finished * 100)}%` : "—", "Among finished evaluations"]]
    .map(([label, value, description]) => `<div class="card stat-card"><p class="card-system-tag">METRICS // ${label}</p><strong class="stat-value">${value}</strong>
      <span class="text-muted">${description}</span></div>`).join("");
}

export function adminTable(data, tab, query) {
  const logs = tab === "evaluations";
  const columns = logs ? ["Evaluation", "Student", "Exercise", "Result", "Timing", "Details"] : ["Student", "Exercise", "State", "SSH port", "Expires", "Actions"];
  return card(logs ? "EVALUATIONS // AUDIT LOG" : "RUNTIMES // ACTIVE OPERATIONS", `<div class="table-responsive"><table>
    <thead><tr>${columns.map((c) => `<th scope="col">${c}</th>`).join("")}</tr></thead><tbody>${data.items.map((x) => `<tr>
      ${logs ? `<td><code title="${e(x.id)}">${e(x.id.slice(0, 8))}</code></td>` : ""}<td>${auditLink("user_id", x.user_id, x.email)}</td><td>${auditLink("exercise_id", x.exercise_id, x.exercise_id)}</td><td>${tag(x.status, x.is_success)}
      ${logs ? (x.error_code || x.error_message ? `<small class="text-error">${e([x.error_code, x.error_message].filter(Boolean).join(": "))}</small>` : "") :
        `<small title="Last state update: ${e(date(x.last_activity_at))}">Updated ${duration(Date.now() - new Date(x.last_activity_at))} ago</small>
        <details class="operation-details"><summary>Operation details</summary>Student: <code>${e(x.user_id)}</code><br>Operation: <code>${e(x.current_operation_id || "—")}</code></details>`}</td>
      ${logs ? `<td>Submitted ${e(date(x.created_at))}<small>Finished ${e(date(x.finished_at))}</small><small>Elapsed ${evaluationTime(x)}${x.finished_at ? "" : " · in progress"}</small></td><td>${button("Details", "summary", x.id)}</td>` :
        `<td>${e(x.ssh_port ?? "—")}</td><td>${e(date(x.expires_at))}<small>${x.expires_at ? new Date(x.expires_at) <= new Date() ? "Expired · awaiting cleanup" : `${duration(new Date(x.expires_at) - Date.now())} remaining` : "No expiration set"}</small></td><td><button class="btn btn-danger" data-action="clear" data-value="${e(x.user_id)}" ${x.status !== "running" ? "disabled" : ""}>Stop environment</button></td>`}
    </tr>`).join("") || `<tr><td colspan="6">No records found.</td></tr>`}</tbody></table></div>`) + (tab === "overview" ? "" : pager(data, (offset) => {
      const next = new URLSearchParams(query); next.set("offset", offset);
      return `#admin/${tab}?${next}`;
    }));
}
