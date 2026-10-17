import { api, escape as e, id, button, tag } from "./api.js";
import * as views from "./views.js";

const $ = (selector) => document.querySelector(selector);
const main = $("#main"), banner = $("#runtime-banner"), dialog = $("#report-dialog");
let user, environment, busy = false, reading, page, reportData, reportController, tick = 0;
const locked = () => busy || !environment || environment.locked;

function notify(message) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  $("#toasts").replaceChildren(toast);
  setTimeout(() => toast.remove(), 5000);
}
function fail(error) {
  if (error.name === "AbortError") return;
  if (error.status === 401 && user) return signIn();
  notify(error.message);
}
function signIn() { location.hash = "login"; location.reload(); }
function closeReport() { reportController?.abort(); reportData = null; dialog.close(); }
async function openReport(value) {
  closeReport();
  dialog.showModal();
  $("#report-body").textContent = "Loading evaluation…";
  reportController = new AbortController();
  if (typeof value === "object") {
    $("#report-body").innerHTML = views.report(value);
  } else {
    reportData = { id: value, status: "running" };
    await refreshReport();
  }
}
async function refreshReport() {
  const controller = reportController;
  try {
    const data = await api(`/evaluations/${id(reportData.id)}`, { signal: controller.signal });
    if (!controller.signal.aborted) {
      reportData = data;
      $("#report-body").innerHTML = views.report(data);
    }
  } catch (error) { fail(error); }
}

// One shared environment read; mutations wait for an older read before fetching again.
function readEnvironment() {
  return reading ||= api("/environment", { signal: AbortSignal.timeout(10000) }).then((data) => { environment = data; })
    .catch((error) => { environment = null; throw error; }).finally(() => { reading = null; });
}
function updateControls() {
  const env = environment?.environment, running = env?.status === "running";
  const status = !environment ? "unknown" : busy ? "pending" : env?.status || "grading";
  banner.hidden = !user || (!!environment && !busy && !environment.locked && (!env || env.status === "stopped"));
  banner.className = `runtime-banner ${status}`;
  banner.innerHTML = banner.hidden ? "" : `<div class="banner-content"><span class="banner-status"><span class="status-dot"></span>
    ${e({ running: "ACTIVE ENVIRONMENT", starting: "STARTING ENVIRONMENT…", stopping: "STOPPING ENVIRONMENT…", grading: "GRADING IN PROGRESS — CONTROLS LOCKED", pending: "REQUEST IN PROGRESS…", unknown: "CHECKING ENVIRONMENT — CONTROLS LOCKED" }[status] || status)}</span>
    <div class="banner-details">${env ? `<a class="banner-exercise" href="#exercises/${id(env.exercise_id)}">${e(env.exercise_id)}</a>` : ""}
    ${running && !locked() && env.ssh ? `<div class="ssh-container"><code class="ssh-command">${e(env.ssh.command)}</code>${button("Copy", "copy")}</div>` : ""}</div>
    <button class="btn btn-danger" data-action="stop" ${locked() || !running ? "disabled" : ""}>■ Stop</button></div>`;
  if (page?.name === "exercises" && page.exercise) {
    const x = page.exercise, expired = x.deadline && new Date(x.deadline) <= new Date();
    const start = main.querySelector('[data-action="start"]'), grade = main.querySelector('[data-action="grade"]');
    if (!start || !grade) return;
    start.disabled = locked() || expired || running || !user.has_ssh_key;
    grade.disabled = locked() || expired || !running || env.exercise_id !== x.id || x.quota.remaining <= 0;
    main.querySelector('[data-action="stop"]').disabled = locked() || !running;
    $("#exercise-meta").innerHTML = tag(x.difficulty) + tag("not passed", x.is_completed) +
      `<span class="tag">QUOTA: ${x.quota.remaining}/${x.quota.limit} (${x.quota.window_minutes}M)</span>`;
    const message = !environment ? "Environment status unavailable. Controls remain locked." : locked() ? "Operation in progress. Controls are locked until cleanup finishes." :
      expired ? "The module deadline has passed." : !user.has_ssh_key ? "Register your SSH public key in Profile before starting." :
      running && env.exercise_id !== x.id ? "Stop the active environment, then start this exercise's environment before evaluating." :
      !running ? "Start this exercise's environment before evaluating." :
      x.quota.remaining <= 0 ? `Evaluation quota exhausted. Retry after ${new Date(x.quota.retry_at).toLocaleTimeString()}.` : "";
    $("#operation-notice").textContent = message;
    $("#operation-notice").hidden = !message;
  }
  const keyForm = main.querySelector('[data-form="key"]');
  if (keyForm) {
    keyForm.querySelector("button").disabled = locked() || (env && env.status !== "stopped");
    $("#key-status").textContent = `SSH KEY // ${user.has_ssh_key ? "CONFIGURED" : "NOT CONFIGURED"}` +
      (keyForm.querySelector("button").disabled ? " · Stop your environment before replacing the key." : "");
  }
}

async function refreshPage(current = page) {
  if (!user || !current?.ready || current.refreshing) return;
  current.refreshing = true;
  const read = (path) => api(path, { signal: current.controller.signal });
  try {
    if (current.name === "exercises") {
      const path = `/exercises/${id(current.key)}`;
      const [exercise, history] = await Promise.all([read(path), read(`${path}/evaluations?limit=10&offset=${current.offset}`)]);
      if (current.controller.signal.aborted) return;
      current.exercise = exercise;
      $("#history").innerHTML = views.history(history, current.key);
      updateControls();
    } else if (current.name === "admin") {
      const query = new URLSearchParams(current.query);
      query.set("limit", current.key === "overview" ? 5 : 25);
      const [stats, rows] = await Promise.all([read("/admin/stats"), read(`/admin/${current.key === "evaluations" ? "evaluations" : "environments"}?${query}`)]);
      if (current.controller.signal.aborted) return;
      current.rows = rows.items;
      $("#admin-stats").innerHTML = views.adminStats(stats);
      $("#admin-panel").innerHTML = views.adminTable(rows, current.key, current.query);
    }
  } catch (error) { fail(error); }
  finally { current.refreshing = false; }
}

async function route() {
  page?.controller.abort();
  closeReport();
  const [path, search = ""] = location.hash.slice(1).split("?");
  const [name, key] = (path || "courses").split("/");
  const query = new URLSearchParams(search);
  const current = page = { name, key, query, offset: Math.max(0, Number(query.get("offset")) || 0), controller: new AbortController() };
  const read = (path) => api(path, { signal: current.controller.signal });
  main.textContent = "Loading…";
  try {
    let html;
    if (!user) html = views.login();
    else if (name === "courses") html = key ? views.course(await read(`/courses/${key}`)) : views.courses(await read("/courses"));
    else if (name === "exercises" && key) {
      current.key = decodeURIComponent(key);
      current.exercise = await read(`/exercises/${key}`);
      html = views.exercise(current.exercise);
    } else if (name === "profile") html = views.profile(user);
    else if (name === "admin" && user.role === "admin") {
      current.key = ["overview", "environments", "evaluations"].includes(key) ? key : "overview";
      html = views.admin(current.key, query);
    } else { location.hash = "courses"; return; }
    if (current.controller.signal.aborted) return;
    main.innerHTML = html;
    main.querySelectorAll(".markdown-body a").forEach((link) => {
      link.target = "_blank"; link.rel = "noopener noreferrer";
    });
    current.ready = true;
    document.title = `${current.exercise?.name || ({ profile: "Profile & Settings", admin: "Platform Administration" }[name]) || (user ? "DevOps Modules" : "Sign in")} — EvalOps`;
    document.querySelectorAll("[data-nav]").forEach((a) => a.toggleAttribute("aria-current", a.dataset.nav === (name === "exercises" ? "courses" : name)));
    updateControls();
    await refreshPage(current);
  } catch (error) {
    if (current.controller.signal.aborted) return;
    main.innerHTML = `<p class="alert alert-error">${e(error.message)}</p>${button("Try again", "refresh")}`;
    fail(error);
  }
}

async function mutate(path) {
  if (locked()) return;
  const origin = page;
  busy = true; updateControls();
  try {
    const result = await api(path, { method: "POST" });
    if (reading) await reading.catch(() => {});
    await readEnvironment();
    if (result.id && page === origin) await openReport(result.id);
    await refreshPage();
  } catch (error) { environment = null; fail(error); }
  finally { busy = false; updateControls(); }
}

document.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-action]");
  if (!target || target.disabled) return;
  const { action, value } = target.dataset;
  try {
    if (action === "start" || action === "grade") await mutate(`/exercises/${id(value)}/${action}`);
    else if (action === "stop") await mutate("/environment/stop");
    else if (action === "copy") {
      const code = $(".ssh-command");
      try { await navigator.clipboard.writeText(code.textContent); notify("SSH command copied."); }
      catch { window.getSelection().selectAllChildren(code); notify("Copy the highlighted command."); }
    } else if (action === "report") await openReport(value);
    else if (action === "summary") await openReport(page.rows.find((x) => x.id === value));
    else if (action === "refresh") { if (page.ready) await refreshPage(); else await route(); }
    else if (action === "clear") {
      target.disabled = true;
      await api(`/admin/environments/${id(value)}/clear`, { method: "POST" });
      notify("Stop requested. Files will be preserved.");
      await refreshPage();
    }
  } catch (error) { target.disabled = false; fail(error); }
});

document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!form.dataset.form) return;
  event.preventDefault();
  const values = Object.fromEntries(new FormData(form)), kind = form.dataset.form;
  if (kind === "filters") {
    const query = new URLSearchParams(Object.entries(values).filter(([, value]) => value.trim()));
    location.hash = `admin/evaluations?${query}`;
    return;
  }
  if (busy || form.querySelector("button").disabled) return;
  busy = true; form.querySelector("button").disabled = true; updateControls();
  try {
    if (kind === "login") {
      await api("/auth/login", { method: "POST", body: values });
      location.hash = "courses"; location.reload();
    } else if (kind === "key") {
      const result = await api("/profile/ssh-key", { method: "PUT", body: values });
      user.has_ssh_key = true; form.reset(); notify("Key saved: " + result.fingerprint);
    } else if (kind === "password") {
      if (values.new_password !== values.confirm) throw new Error("The new passwords do not match.");
      await api("/profile/password", { method: "PUT", body: { current_password: values.current_password, new_password: values.new_password } });
      signIn();
    }
  } catch (error) { fail(error); }
  finally { busy = false; form.querySelector("button").disabled = false; updateControls(); }
});

async function poll() {
  if (user && !document.hidden) {
    const previous = JSON.stringify(environment);
    try { await readEnvironment(); }
    catch (error) { if (error.status === 401) fail(error); }
    updateControls();
    if (++tick % 5 === 0 || previous !== JSON.stringify(environment)) await refreshPage();
    if (dialog.open && reportData?.status === "running" && !reportData.finished_at) await refreshReport();
  }
  setTimeout(poll, 2000);
}
$("#report-close").onclick = closeReport;
$(".skip-link").onclick = (event) => { event.preventDefault(); main.focus(); };
dialog.addEventListener("close", () => { reportController?.abort(); reportData = null; });
$("#logout").onclick = async () => {
  if (busy) return;
  busy = true; updateControls();
  try { await api("/auth/logout", { method: "POST" }); signIn(); }
  catch (error) { fail(error); busy = false; updateControls(); }
};
window.addEventListener("hashchange", route);
async function boot() {
  try { user = (await api("/auth/me")).user; }
  catch (error) {
    if (error.status !== 401) {
      main.innerHTML = `<p class="alert alert-error">${e(error.message)}</p>${button("Try again", "refresh")}`;
      // Retry a failed connection without requiring a signed-in session.
      main.querySelector("button").onclick = () => location.reload();
      return;
    }
  }
  $("#app-nav").hidden = !user;
  $("#user-email").textContent = user?.email || "";
  $("#nav-admin").hidden = $("#user-role").hidden = user?.role !== "admin";
  await route();
  poll();
}
boot();
