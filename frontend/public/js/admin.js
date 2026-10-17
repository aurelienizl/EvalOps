import { api, escape as e, date, button, pager } from "./api.js";
import { outcomes, outcome, offsetOf, requestQuery, adminHref, progressPercent, filteredQuery } from "./admin-data.js";

const badge = (key) => {
  const [label, tone] = outcomes[key] || outcomes.none;
  return `<span class="teacher-badge teacher-badge-${tone}">${label}</span>`;
};
const runtime = (state) => {
  const label = { running: "Workspace running", starting: "Starting", stopping: "Stopping", grading: "Grading", stopped: "Stopped" }[state] || "No workspace";
  return `<span class="teacher-runtime ${state === "running" ? "is-running" : ""}"><span aria-hidden="true"></span>${label}</span>`;
};
const studentButton = (student, email) => `<button type="button" class="teacher-student-link" data-action="admin-student" data-value="${e(student)}">${e(email)}</button>`;
const latest = (row) => badge(outcome({ status: row.latest_status, is_success: row.latest_is_success }));
const empty = (text) => `<div class="teacher-empty"><strong>No results to show</strong><p>${e(text)}</p></div>`;
const courseName = (current) => current.courses?.find((x) => x.id === current.query.get("course_id"))?.name || "All courses";

export function shell(tab, query) {
  const tabs = [["overview", "Class overview"], ["evaluations", "Submissions"], ["environments", "Workspaces"]];
  return `<section class="teacher-dashboard">
    <header class="teacher-header"><div><p class="card-system-tag">EVALOPS / TEACHING</p>
      <h1>Classroom overview</h1><p class="text-muted">Follow student progress and see where a closer look could help.</p></div>
      <div class="teacher-refresh"><span id="admin-updated" class="text-muted" aria-live="off">Connecting…</span>${button("Refresh", "refresh")}</div></header>
    <p class="teacher-stats-scope">Platform totals · All courses</p><div id="admin-stats" class="teacher-metrics" aria-label="Platform totals"></div>
    <nav class="teacher-tabs" aria-label="Teaching views">${tabs.map(([key, label]) =>
      `<a href="${e(adminHref(key, requestQuery(query, ["course_id", "search"])))}" ${key === tab ? 'aria-current="page"' : ""}>${label}</a>`).join("")}</nav>
    <form class="teacher-filters" data-form="admin-filters">
      <div class="teacher-filter-field"><label for="admin-course">Course</label><select name="course_id" id="admin-course"><option value="">All courses</option></select></div>
      <div class="teacher-filter-field teacher-search"><label for="admin-search">Find a student</label><input id="admin-search" type="search" name="search" value="${e(query.get("search"))}" placeholder="Search by email" maxlength="255" autocomplete="off"></div>
      ${tab === "evaluations" ? `<div class="teacher-filter-field"><label for="admin-outcome">Result</label><select id="admin-outcome" name="outcome"><option value="">All results</option>${Object.entries(outcomes).filter(([key]) => key !== "none").map(([key, [label]]) =>
        `<option value="${key}" ${key === query.get("outcome") ? "selected" : ""}>${label}</option>`).join("")}</select></div>` : ""}
      <button class="btn btn-primary" type="submit">Apply filters</button><a class="btn" href="#admin/${tab}">Reset</a>
    </form>
    <div id="admin-filter-context"></div><p id="admin-error" class="alert alert-error" role="status" hidden></p>
    <div id="admin-panel" aria-label="${tabs.find(([key]) => key === tab)?.[1]}"><p class="text-muted">Loading classroom data…</p></div>
    <aside id="admin-student-panel" class="teacher-drawer" aria-label="Student details" hidden>
      <header class="teacher-drawer-header"><div><p class="card-system-tag">STUDENT DETAILS</p><h2 id="admin-student-title" tabindex="-1">Student</h2></div>
      <button type="button" class="btn btn-ghost" data-action="admin-close-student" aria-label="Close student details">×</button></header>
      <div id="admin-student-body" class="teacher-drawer-body"></div>
    </aside></section>`;
}

// Keep the search form, focus, horizontal scroll and open details stable on polling.
function patchRegion(selector, html) {
  const node = document.querySelector(selector);
  if (!node) return;
  const template = document.createElement("template");
  template.innerHTML = html;
  const open = new Set([...node.querySelectorAll("details[open][data-key]")].map((x) => x.dataset.key));
  template.content.querySelectorAll("details[data-key]").forEach((x) => { x.open = open.has(x.dataset.key); });
  if (node.innerHTML === template.innerHTML) return;
  const focused = node.contains(document.activeElement) ? document.activeElement : null;
  const identity = focused?.dataset;
  const scroll = [...node.querySelectorAll(".table-responsive")].map((x) => x.scrollLeft);
  const top = node.scrollTop;
  node.replaceChildren(template.content);
  node.scrollTop = top;
  node.querySelectorAll(".table-responsive").forEach((x, i) => { x.scrollLeft = scroll[i] || 0; });
  if (identity?.action) [...node.querySelectorAll("[data-action]")].find((x) =>
    x.dataset.action === identity.action && x.dataset.value === identity.value)?.focus({ preventScroll: true });
}

function metrics(stats) {
  return [["Student accounts", stats.students, "Across all courses", "#admin/overview"],
    ["Active workspaces", stats.active_environments, "Running or changing state", "#admin/environments"],
    ["Awaiting results", stats.pending_evaluations, "Queued or grading", "#admin/evaluations?outcome=grading"],
    ["Validated submissions", stats.successful_evaluations, "All-time successful attempts", "#admin/evaluations?outcome=validated"]]
    .map(([label, value, hint, href]) => `<a class="teacher-metric" href="${href}"><span>${label}</span><strong>${value}</strong><small>${hint}</small></a>`).join("");
}

function progress(student, total) {
  return `<div class="teacher-progress"><div><strong>${student.validated_exercises}<span> / ${total}</span></strong><span>${progressPercent(student.validated_exercises, total)}%</span></div>
    <progress max="${Math.max(total, 1)}" value="${student.validated_exercises}" aria-label="Validated exercises"></progress></div>`;
}

function section(title, count, description, body, pagination = "") {
  return `<section class="teacher-section"><header class="teacher-section-header"><div><h2>${title}<span class="teacher-count">${count}</span></h2><p>${e(description)}</p></div></header>${body}${pagination}</section>`;
}

function pageLinks(data, current) {
  return `<div class="teacher-pagination">${pager(data, (offset) => adminHref(current.key, current.query, { offset }))}</div>`;
}

function roster(data, current) {
  const body = data.items.length ? `<div class="table-responsive"><table class="teacher-table"><caption class="sr-only">Student progress for ${e(courseName(current))}</caption>
    <thead><tr><th scope="col">Student</th><th scope="col">Validated exercises</th><th scope="col">Current workspace</th><th scope="col">Latest result</th><th scope="col">Last submission</th></tr></thead><tbody>
    ${data.items.map((x) => `<tr><td>${studentButton(x.id, x.email)}<small>${x.submissions} submissions · ${x.attempted_exercises} exercises attempted</small></td>
      <td>${progress(x, data.total_exercises)}</td><td>${runtime(x.environment_status)}${x.environment_status && x.environment_status !== "stopped" ? `<small>${e(x.environment_exercise_name)}</small>` : ""}</td>
      <td>${latest(x)}${x.latest_exercise_name ? `<small>${e(x.latest_exercise_name)}</small>` : ""}</td><td><time>${e(date(x.last_submission_at))}</time></td></tr>`).join("")}</tbody></table></div>` :
    empty(current.query.get("search") ? "Try another email or reset the filters." : "Student accounts will appear here, including students with no submissions.");
  return section("Students", data.total, `All student accounts · ${courseName(current)} · Each validated exercise counts once.`, body, pageLinks(data, current));
}

function submissionRows(rows, compact = false) {
  return rows.map((x) => `<tr>${compact ? "" : `<td>${studentButton(x.user_id, x.email)}</td>`}
    <td><strong>${e(x.exercise_name || x.exercise_id)}</strong></td><td>${badge(outcome(x))}${x.error_message ? `<small class="text-error">${e(x.error_message)}</small>` : ""}</td>
    <td>${x.status === "running" ? "—" : `${x.passed_tests} / ${x.total_tests}`}</td><td><time>${e(date(x.created_at))}</time></td>
    <td>${button("View report", "admin-report", x.id)}</td></tr>`).join("");
}

function submissions(data, current) {
  const body = data.items.length ? `<div class="table-responsive"><table class="teacher-table"><caption class="sr-only">Student submissions</caption><thead><tr>
    <th scope="col">Student</th><th scope="col">Exercise</th><th scope="col">Result</th><th scope="col">Tests passed</th><th scope="col">Submitted</th><th scope="col"><span class="sr-only">Report</span></th></tr></thead><tbody>${submissionRows(data.items)}</tbody></table></div>` : empty("No submissions match these filters.");
  return section("Submissions", data.total, `${courseName(current)} · Unsuccessful means one or more submission checks failed.`, body, pageLinks(data, current));
}

function stopButton(user, state, current) {
  const pending = current.pendingStops?.has(user);
  return `<button type="button" class="btn btn-danger" data-action="admin-stop" data-value="${e(user)}" ${state !== "running" || pending ? "disabled" : ""}>${pending ? "Stopping…" : "Stop workspace"}</button>`;
}

function workspaces(data, current) {
  const body = data.items.length ? `<div class="table-responsive"><table class="teacher-table"><caption class="sr-only">Active student workspaces</caption><thead><tr>
    <th scope="col">Student</th><th scope="col">Exercise</th><th scope="col">Workspace</th><th scope="col">Expires</th><th scope="col">Actions</th></tr></thead><tbody>${data.items.map((x) => `<tr>
      <td>${studentButton(x.user_id, x.email)}</td><td><strong>${e(x.exercise_name)}</strong></td><td>${runtime(x.status)}</td><td>${e(date(x.expires_at))}</td>
      <td>${stopButton(x.user_id, x.status, current)}<details class="teacher-technical" data-key="${e(x.user_id)}"><summary>Connection details</summary><p>SSH port: ${e(x.ssh_port ?? "—")}</p><p>State updated: ${e(date(x.last_activity_at))}</p></details></td></tr>`).join("")}</tbody></table></div>` : empty("There are no active workspaces matching these filters.");
  return section("Workspaces", data.total, "Starting, running, grading and stopping workspaces. Stopping a workspace preserves student files.", body, pageLinks(data, current));
}

function updateCourseOptions(current) {
  if (current.courseOptionsReady) return;
  const selected = current.query.get("course_id") || "";
  const options = [{ id: "", name: "All courses" }, ...current.courses];
  if (selected && !options.some((x) => x.id === selected)) options.push({ id: selected, name: "Unavailable course" });
  patchRegion("#admin-course", options.map((x) => `<option value="${e(x.id)}" ${x.id === selected ? "selected" : ""}>${e(x.name)}</option>`).join(""));
  current.courseOptionsReady = true;
}

export async function refresh(current) {
  const version = current.adminVersion = (current.adminVersion || 0) + 1;
  const signal = current.controller.signal;
  const query = requestQuery(current.query, current.key === "evaluations" ?
    ["course_id", "search", "user_id", "exercise_id", "status", "outcome"] : ["course_id", "search"],
  { limit: 25, offset: offsetOf(current.query.get("offset")) });
  const resource = current.key === "overview" ? "students" : current.key;
  const [stats, data, catalog] = await Promise.all([
    api("/admin/stats", { signal }), api(`/admin/${resource}?${query}`, { signal }),
    current.courses ? Promise.resolve({ items: current.courses }) : api("/courses", { signal }),
  ]);
  if (signal.aborted || current.adminVersion !== version) return;
  current.courses = catalog.items;
  updateCourseOptions(current);
  patchRegion("#admin-stats", metrics(stats));
  const filterChips = ["user_id", "exercise_id", "status"].filter((key) => current.query.has(key));
  patchRegion("#admin-filter-context", filterChips.length ? `<div class="teacher-filter-chips">${filterChips.map((key) =>
    `<a href="${e(adminHref(current.key, current.query, { [key]: null, offset: null }))}" class="teacher-filter-chip">${e(key === "user_id" ? "Selected student" : current.query.get(key))} <span aria-label="Remove filter">×</span></a>`).join("")}</div>` : "");
  const render = current.key === "overview" ? roster : current.key === "environments" ? workspaces : submissions;
  patchRegion("#admin-panel", render(data, current));
  document.querySelector("#admin-updated").textContent = "Updated " + new Date().toLocaleTimeString();
  document.querySelector("#admin-error").hidden = true;
  if (current.query.has("student")) await refreshStudent(current);
}

export function showError(error) {
  const node = document.querySelector("#admin-error");
  if (node && error.name !== "AbortError") { node.textContent = error.message + " Use Refresh to try again."; node.hidden = false; }
}

export async function refreshStudent(current) {
  const selected = current.query.get("student");
  const panel = document.querySelector("#admin-student-panel");
  if (!selected || !panel) return;
  panel.hidden = false;
  const version = current.studentVersion = (current.studentVersion || 0) + 1;
  const signal = current.controller.signal;
  const isCurrent = () => !signal.aborted && current.studentVersion === version && current.query.get("student") === selected;
  const course = current.query.get("course_id");
  const query = new URLSearchParams({ user_id: selected, limit: 1 });
  if (course) query.set("course_id", course);
  const historyQuery = new URLSearchParams(query);
  historyQuery.set("limit", 10);
  historyQuery.set("offset", offsetOf(current.query.get("student_offset")));
  try {
    const [students, history] = await Promise.all([
      api(`/admin/students?${query}`, { signal }), api(`/admin/evaluations?${historyQuery}`, { signal }),
    ]);
    if (!isCurrent()) return;
    const student = students.items[0];
    document.querySelector("#admin-student-title").textContent = student?.email || "Student unavailable";
    if (!student) { patchRegion("#admin-student-body", empty("This student account could not be found.")); return; }
    const links = requestQuery(current.query, ["course_id"], { user_id: selected });
    const pages = `<div class="teacher-drawer-pages"><button type="button" class="btn" data-action="admin-student-page" data-value="${Math.max(0, history.offset - history.limit)}" ${history.offset === 0 ? "disabled" : ""}>Previous</button><span>${history.total ? history.offset + 1 : 0}–${Math.min(history.offset + history.limit, history.total)} / ${history.total}</span><button type="button" class="btn" data-action="admin-student-page" data-value="${history.offset + history.limit}" ${history.offset + history.limit >= history.total ? "disabled" : ""}>Next</button></div>`;
    patchRegion("#admin-student-body", `<section class="teacher-student-progress"><div class="teacher-section-label">${e(courseName(current))}</div><h3>Exercise progress</h3>${progress(student, students.total_exercises)}
      <p>${student.attempted_exercises} exercises with submissions · ${student.submissions} submissions</p><p class="text-muted">A validation is kept even if a later attempt is unsuccessful.</p></section>
      <section class="teacher-student-runtime"><h3>Current workspace</h3>${runtime(student.environment_status)}
      ${student.environment_status && student.environment_status !== "stopped" ? `<p>${e(student.environment_exercise_name)}</p><p class="text-muted">Expires ${e(date(student.expires_at))}</p>${stopButton(student.id, student.environment_status, current)}` : '<p class="text-muted">No active workspace. Saved files are preserved.</p>'}</section>
      <section class="teacher-student-history"><div class="teacher-history-heading"><h3>Submission history</h3><a href="${e(adminHref("evaluations", links))}">View all →</a></div>
      ${history.items.length ? `<div class="table-responsive"><table><caption class="sr-only">Submissions by ${e(student.email)}</caption><thead><tr><th>Exercise</th><th>Result</th><th>Tests</th><th>Submitted</th><th><span class="sr-only">Report</span></th></tr></thead><tbody>${submissionRows(history.items, true)}</tbody></table></div>${pages}` : '<p class="text-muted">No submissions for this course yet.</p>'}</section>`);
    if (current.focusStudentPanel) { document.querySelector("#admin-student-title").focus({ preventScroll: true }); current.focusStudentPanel = false; }
  } catch (error) {
    if (!isCurrent()) return;
    patchRegion("#admin-student-body", `<p class="alert alert-error">${e(error.message)}</p>${button("Try again", "admin-student", selected)}`);
    throw error;
  }
}

function remember(current) {
  history.replaceState(null, "", adminHref(current.key, current.query));
}

export async function handleClick(action, value, current) {
  if (action === "admin-student") {
    current.query.set("student", value); current.query.delete("student_offset"); current.focusStudentPanel = true;
    remember(current);
    document.querySelector("#admin-student-title").textContent = "Loading student…";
    patchRegion("#admin-student-body", '<p class="text-muted">Loading student details…</p>');
    await refreshStudent(current);
  } else if (action === "admin-close-student") {
    const selected = current.query.get("student");
    current.query.delete("student"); current.query.delete("student_offset"); current.studentVersion = (current.studentVersion || 0) + 1;
    document.querySelector("#admin-student-panel").hidden = true;
    remember(current);
    [...document.querySelectorAll('[data-action="admin-student"]')].find((x) => x.dataset.value === selected)?.focus({ preventScroll: true });
  } else if (action === "admin-student-page") {
    current.query.set("student_offset", offsetOf(value)); remember(current); await refreshStudent(current);
  } else if (action === "admin-stop") {
    current.pendingStops ||= new Set();
    if (current.pendingStops.has(value)) return;
    current.pendingStops.add(value);
    document.querySelectorAll('[data-action="admin-stop"]').forEach((x) => { if (x.dataset.value === value) { x.disabled = true; x.textContent = "Stopping…"; } });
    try { await api(`/admin/environments/${encodeURIComponent(value)}/clear`, { method: "POST" }); }
    finally {
      current.pendingStops.delete(value);
      if (!current.controller.signal.aborted) await refresh(current);
    }
  }
}

export function applyFilters(values, current) {
  const query = filteredQuery(current.query, values);
  location.hash = adminHref(current.key, query).slice(1);
}
