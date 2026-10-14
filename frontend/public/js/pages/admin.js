import { $, apiCall, formatDate, showMessage, showToast, state } from "../core.js";
import { showEvaluationModal } from "./exercise.js";
import { escapeHtml } from "../html.js";

// Internal admin page state
const adminState = {
  currentTab: "tab-overview",
  users: {
    search: "",
    role: "",
    limit: 15,
    offset: 0,
    total: 0,
    items: [],
  },
  evaluations: {
    studentId: "",
    exerciseId: "",
    status: "",
    limit: 15,
    offset: 0,
    total: 0,
    items: [],
  },
};

let initialized = false;
const requestVersions = {};

function beginRequest(section) {
  const version = requestVersions[section] = (requestVersions[section] || 0) + 1;
  const user = state.user;
  const route = state.routeVersion;
  return () => requestVersions[section] === version && user === state.user && route === state.routeVersion;
}

export function initAdminView() {
  if (initialized) return;
  initialized = true;

  // Tab switching
  document.querySelectorAll(".admin-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tabId = btn.dataset.tab;
      switchAdminTab(tabId);
    });
  });

  // Global refresh button
  $("admin-btn-refresh")?.addEventListener("click", async () => {
    await refreshCurrentTab();
    showToast("Admin data refreshed");
  });

  // Create user modal trigger
  $("admin-btn-new-user")?.addEventListener("click", () => {
    openCreateUserModal();
  });

  $("modal-create-user-close")?.addEventListener("click", closeCreateUserModal);
  $("admin-btn-cancel-create")?.addEventListener("click", closeCreateUserModal);
  $("modal-create-user")?.addEventListener("click", (e) => {
    if (e.target === $("modal-create-user")) closeCreateUserModal();
  });

  // Create user form submission
  $("form-admin-create-user")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = $("admin-new-email").value.trim();
    const password = $("admin-new-password").value;
    const role = $("admin-new-role").value;
    const errEl = $("admin-create-user-error");
    const submitBtn = $("admin-btn-submit-create");
    if (submitBtn.disabled) return;
    const user = state.user;

    errEl.classList.add("hidden");
    submitBtn.disabled = true;

    try {
      await apiCall("/api/v1/admin/users", {
        method: "POST",
        body: { email, password, role },
      });
      if (user !== state.user) return;
      showToast(`User ${email} created successfully`);
      closeCreateUserModal();
      $("form-admin-create-user").reset();
      await loadUsersTab();
      await loadOverviewStats();
    } catch (err) {
      if (user !== state.user) return;
      errEl.textContent = err.message || "Failed to create user";
      errEl.classList.remove("hidden");
    } finally {
      submitBtn.disabled = false;
    }
  });

  // Users filters
  let userSearchTimeout = null;
  $("admin-users-search")?.addEventListener("input", (e) => {
    clearTimeout(userSearchTimeout);
    userSearchTimeout = setTimeout(() => {
      adminState.users.search = e.target.value.trim();
      adminState.users.offset = 0;
      loadUsersTab();
    }, 300);
  });

  $("admin-users-role-filter")?.addEventListener("change", (e) => {
    adminState.users.role = e.target.value;
    adminState.users.offset = 0;
    loadUsersTab();
  });

  // Evaluations filters
  let evalFilterTimeout = null;
  const triggerEvalFilter = () => {
    clearTimeout(evalFilterTimeout);
    evalFilterTimeout = setTimeout(() => {
      adminState.evaluations.studentId = $("admin-evals-student-filter").value.trim();
      adminState.evaluations.exerciseId = $("admin-evals-exercise-filter").value.trim();
      adminState.evaluations.status = $("admin-evals-status-filter").value;
      adminState.evaluations.offset = 0;
      loadEvaluationsTab();
    }, 300);
  };

  $("admin-evals-student-filter")?.addEventListener("input", triggerEvalFilter);
  $("admin-evals-exercise-filter")?.addEventListener("input", triggerEvalFilter);
  $("admin-evals-status-filter")?.addEventListener("change", triggerEvalFilter);
}

function switchAdminTab(tabId) {
  adminState.currentTab = tabId;
  document.querySelectorAll(".admin-tab-btn").forEach((btn) => {
    const isActive = btn.dataset.tab === tabId;
    btn.classList.toggle("active", isActive);
    btn.setAttribute("aria-selected", isActive ? "true" : "false");
  });

  document.querySelectorAll(".admin-tab-content").forEach((content) => {
    content.classList.toggle("hidden", content.id !== tabId);
  });

  refreshCurrentTab();
}

async function refreshCurrentTab() {
  if (state.user?.role !== "admin") return;
  const user = state.user;
  const route = state.routeVersion;
  await loadOverviewStats();
  if (user !== state.user || route !== state.routeVersion) return;
  if (adminState.currentTab === "tab-overview") {
    await loadOverviewTab();
  } else if (adminState.currentTab === "tab-users") {
    await loadUsersTab();
  } else if (adminState.currentTab === "tab-environments") {
    await loadEnvironmentsTab();
  } else if (adminState.currentTab === "tab-evaluations") {
    await loadEvaluationsTab();
  }
}

export async function loadAdminView() {
  initAdminView();
  await refreshCurrentTab();
}

// --- OVERVIEW TAB ---

async function loadOverviewStats() {
  const isCurrent = beginRequest("stats");
  try {
    const stats = await apiCall("/api/v1/admin/stats");
    if (!isCurrent()) return;
    $("stat-total-users").textContent = stats.total_users ?? "-";
    $("stat-total-evals").textContent = stats.total_evaluations ?? "-";
    $("stat-passed-evals").textContent = stats.passed_evaluations ?? "-";
    $("stat-active-ops").textContent = stats.active_operations ?? "0";

    const passRate = stats.total_evaluations > 0
      ? Math.round((stats.passed_evaluations / stats.total_evaluations) * 100)
      : 0;
    $("stat-pass-rate").textContent = `Pass Rate (${passRate}%)`;

    // Badges in tabs
    $("admin-users-badge").textContent = stats.total_users ?? "-";
    $("admin-env-badge").textContent = stats.active_operations ?? "0";
    $("admin-eval-badge").textContent = stats.total_evaluations ?? "-";
  } catch (err) {
    console.error("Failed to load platform stats:", err);
  }
}

async function loadOverviewTab() {
  const container = $("admin-overview-active-env");
  if (!container) return;
  const isCurrent = beginRequest("overview");

  try {
    const data = await apiCall("/api/v1/admin/environments");
    if (!isCurrent()) return;
    const runtimes = data.active_environments;
    if (runtimes.length === 0) {
      showMessage(container, "No active operations.", "text-muted mono empty-message");
      return;
    }

    container.replaceChildren();
    const list = document.createElement("div");
    list.className = "admin-active-grid";

    for (const r of runtimes) {
      const item = document.createElement("div");
      item.className = "admin-active-card";
      item.innerHTML = `
        <div class="admin-active-header">
          <span class="status-dot"></span>
          <strong class="text-white">${escapeHtml(r.email)}</strong>
          <span class="tag tag-status">${escapeHtml(r.operation_type.toUpperCase())} // ${escapeHtml(r.phase.toUpperCase())}</span>
        </div>
        <div class="admin-active-meta mono text-muted">
          <span>Exercise: ${escapeHtml(r.exercise_id || "N/A")}</span>
          <span>Started: ${escapeHtml(formatDate(r.started_at))}</span>
        </div>
        <div class="admin-active-actions">
          <button class="btn btn-danger btn-sm btn-unlock">
            CLEAR STALE STATE
          </button>
        </div>
      `;

      const unlockButton = item.querySelector(".btn-unlock");
      unlockButton.addEventListener("click", async () => {
        if (!isCurrent() || unlockButton.disabled) return;
        unlockButton.disabled = true;
        try { await forceUnlock(r.student_id, r.email); }
        finally { unlockButton.disabled = false; }
      });
      list.appendChild(item);
    }
    container.appendChild(list);
  } catch (err) {
    if (!isCurrent()) return;
    showMessage(container, `Failed to load active runtimes: ${err.message}`, "alert alert-error");
  }
}

// --- USERS TAB ---

async function loadUsersTab() {
  const tbody = $("admin-users-tbody");
  const pagination = $("admin-users-pagination");
  if (!tbody) return;
  const isCurrent = beginRequest("users");

  tbody.innerHTML = `<tr><td colspan="5" class="text-muted mono loading-message">Loading users...</td></tr>`;

  const { search, role, limit, offset } = adminState.users;
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (search) params.set("search", search);
  if (role) params.set("role", role);

  try {
    const data = await apiCall(`/api/v1/admin/users?${params.toString()}`);
    if (!isCurrent()) return;
    adminState.users.total = data.total;
    adminState.users.items = data.items;

    if (data.items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="text-muted mono empty-message">No users found matching query.</td></tr>`;
      pagination.replaceChildren();
      return;
    }

    tbody.replaceChildren();
    for (const u of data.items) {
      const tr = document.createElement("tr");
      const isAdmin = u.role === "admin";
      const isSelf = state.user?.id === u.id;
      const hasSsh = !!u.ssh_public_key;

      tr.innerHTML = `
        <td>
          <div class="user-cell">
            <span class="user-email text-white">${escapeHtml(u.email)}</span>
            <span class="user-id mono text-dim">${escapeHtml(u.id)}</span>
          </div>
        </td>
        <td>
          <span class="tag ${isAdmin ? "tag-role-admin" : "tag-role-student"}">${escapeHtml(u.role.toUpperCase())}</span>
        </td>
        <td>
          <div class="ssh-status-cell">
            <span class="status-dot-sm ${hasSsh ? "dot-active" : "dot-inactive"}"></span>
            <span class="mono ${hasSsh ? "text-main" : "text-dim"}">${hasSsh ? "Configured" : "None"}</span>
          </div>
        </td>
        <td class="mono text-muted">${escapeHtml(formatDate(u.created_at))}</td>
        <td class="text-right">
          ${isSelf
            ? `<span class="mono text-dim">CURRENT USER</span>`
            : `<button class="btn btn-secondary btn-sm btn-change-role">
                ${isAdmin ? "Demote to Student" : "Promote to Admin"}
               </button>`
          }
        </td>
      `;

      const changeRoleBtn = tr.querySelector(".btn-change-role");
      if (changeRoleBtn) {
        changeRoleBtn.addEventListener("click", async () => {
          if (!isCurrent() || changeRoleBtn.disabled) return;
          const targetRole = isAdmin ? "student" : "admin";
          const actionText = isAdmin ? "demote to student" : "promote to admin";
          if (!confirm(`Are you sure you want to ${actionText} user ${u.email}?`)) return;

          try {
            changeRoleBtn.disabled = true;
            await apiCall(`/api/v1/admin/users/${encodeURIComponent(u.id)}/role`, {
              method: "PUT",
              body: { role: targetRole },
            });
            if (!isCurrent()) return;
            showToast(`Role updated for ${u.email}`);
            await loadUsersTab();
          } catch (err) {
            if (!isCurrent()) return;
            showToast(`Error: ${err.message}`, 5000);
          } finally {
            changeRoleBtn.disabled = false;
          }
        });
      }

      tbody.appendChild(tr);
    }

    renderPagination(
      pagination,
      adminState.users.total,
      adminState.users.limit,
      adminState.users.offset,
      (newOffset) => {
        adminState.users.offset = newOffset;
        loadUsersTab();
      }
    );
  } catch (err) {
    if (!isCurrent()) return;
    pagination.replaceChildren();
    tbody.innerHTML = `<tr><td colspan="5" class="alert alert-error">${escapeHtml(err.message)}</td></tr>`;
  }
}

// --- ENVIRONMENTS TAB ---

async function loadEnvironmentsTab() {
  const tbody = $("admin-env-tbody");
  if (!tbody) return;
  const isCurrent = beginRequest("environments");

  tbody.innerHTML = `<tr><td colspan="6" class="text-muted mono loading-message">Querying active runtimes...</td></tr>`;

  try {
    const data = await apiCall("/api/v1/admin/environments");
    if (!isCurrent()) return;
    const runtimes = data.active_environments;

    if (runtimes.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-muted mono empty-message">No active operations.</td></tr>`;
      return;
    }

    tbody.replaceChildren();
    for (const r of runtimes) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>
          <div class="user-cell">
            <span class="user-email text-white">${escapeHtml(r.email)}</span>
            <span class="user-id mono text-dim">${escapeHtml(r.student_id)}</span>
          </div>
        </td>
        <td><span class="tag tag-status">${escapeHtml(r.operation_type.toUpperCase())}</span></td>
        <td class="mono text-main">${escapeHtml(r.exercise_id || "N/A")}</td>
        <td><span class="tag tag-neutral">${escapeHtml(r.phase.toUpperCase())}</span></td>
        <td class="mono text-muted">${escapeHtml(formatDate(r.started_at))}</td>
        <td class="text-right">
          <button class="btn btn-danger btn-sm btn-unlock-row">
            CLEAR STALE STATE
          </button>
        </td>
      `;

      const unlockButton = tr.querySelector(".btn-unlock-row");
      unlockButton.addEventListener("click", async () => {
        if (!isCurrent() || unlockButton.disabled) return;
        unlockButton.disabled = true;
        try { await forceUnlock(r.student_id, r.email); }
        finally { unlockButton.disabled = false; }
      });

      tbody.appendChild(tr);
    }
  } catch (err) {
    if (!isCurrent()) return;
    tbody.innerHTML = `<tr><td colspan="6" class="alert alert-error">${escapeHtml(err.message)}</td></tr>`;
  }
}

async function forceUnlock(studentId, email) {
  if (!confirm(`Clear stale operation state for ${email}? Active operations must finish first.`)) return;
  const user = state.user;
  try {
    await apiCall(`/api/v1/admin/environments/${encodeURIComponent(studentId)}/unlock`, {
      method: "POST",
    });
    if (user !== state.user) return;
    showToast(`Unlocked environment for ${email}`);
    await refreshCurrentTab();
  } catch (err) {
    if (user !== state.user) return;
    showToast(`Unlock failed: ${err.message}`, 5000);
  }
}

// --- EVALUATIONS TAB ---

async function loadEvaluationsTab() {
  const tbody = $("admin-evals-tbody");
  const pagination = $("admin-evals-pagination");
  if (!tbody) return;
  const isCurrent = beginRequest("evaluations");

  tbody.innerHTML = `<tr><td colspan="7" class="text-muted mono loading-message">Loading evaluation logs...</td></tr>`;

  const { studentId, exerciseId, status, limit, offset } = adminState.evaluations;
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (studentId) params.set("student_id", studentId);
  if (exerciseId) params.set("exercise_id", exerciseId);
  if (status) params.set("status", status);

  try {
    const data = await apiCall(`/api/v1/admin/evaluations?${params.toString()}`);
    if (!isCurrent()) return;
    adminState.evaluations.total = data.total;
    adminState.evaluations.items = data.items;

    if (data.items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-muted mono empty-message">No evaluation logs found matching filters.</td></tr>`;
      pagination.replaceChildren();
      return;
    }

    tbody.replaceChildren();
    for (const ev of data.items) {
      const tr = document.createElement("tr");
      const isCompleted = ev.status === "completed";
      const isPassed = ev.percentage === 100.0;
      const statusClass = ["error", "interrupted"].includes(ev.status) ? "tag-hard" : isPassed ? "tag-status" : "tag-neutral";

      tr.innerHTML = `
        <td><code class="mono text-muted">${escapeHtml(ev.id.slice(0, 8))}...</code></td>
        <td><code class="mono text-dim">${escapeHtml(ev.student_id ? ev.student_id.slice(0, 8) + '...' : '-')}</code></td>
        <td class="text-white mono">${escapeHtml(ev.exercise_id)}</td>
        <td>
          <span class="mono ${isPassed ? "text-success" : "text-main"}">
            ${escapeHtml(isCompleted ? `${ev.passed}/${ev.total} (${ev.percentage}%)` : "-")}
          </span>
        </td>
        <td><span class="tag ${statusClass}">${escapeHtml(ev.status.toUpperCase())}</span></td>
        <td class="mono text-muted">${escapeHtml(formatDate(ev.created_at))}</td>
        <td class="text-right">
          <button class="btn btn-secondary btn-sm btn-view-eval">
            VIEW REPORT
          </button>
        </td>
      `;

      tr.querySelector(".btn-view-eval").addEventListener("click", () => {
        if (isCurrent()) showEvaluationModal(ev);
      });

      tbody.appendChild(tr);
    }

    renderPagination(
      pagination,
      adminState.evaluations.total,
      adminState.evaluations.limit,
      adminState.evaluations.offset,
      (newOffset) => {
        adminState.evaluations.offset = newOffset;
        loadEvaluationsTab();
      }
    );
  } catch (err) {
    if (!isCurrent()) return;
    pagination.replaceChildren();
    tbody.innerHTML = `<tr><td colspan="7" class="alert alert-error">${escapeHtml(err.message)}</td></tr>`;
  }
}

// --- PAGINATION COMPONENT ---

function renderPagination(container, total, limit, currentOffset, onPageChange) {
  if (!container) return;
  if (total <= limit) {
    container.replaceChildren();
    return;
  }

  const currentPage = Math.floor(currentOffset / limit) + 1;
  const totalPages = Math.ceil(total / limit);

  container.innerHTML = `
    <div class="pagination-info mono text-muted">
      Page ${currentPage} of ${totalPages} (${escapeHtml(total)} total records)
    </div>
    <div class="pagination-buttons">
      <button class="btn btn-secondary btn-sm btn-prev" ${currentPage <= 1 ? "disabled" : ""}>
        ← PREV
      </button>
      <button class="btn btn-secondary btn-sm btn-next" ${currentPage >= totalPages ? "disabled" : ""}>
        NEXT →
      </button>
    </div>
  `;

  container.querySelector(".btn-prev")?.addEventListener("click", () => {
    if (currentPage > 1) onPageChange((currentPage - 2) * limit);
  });

  container.querySelector(".btn-next")?.addEventListener("click", () => {
    if (currentPage < totalPages) onPageChange(currentPage * limit);
  });
}

// --- MODAL UTILS ---

function openCreateUserModal() {
  const modal = $("modal-create-user");
  if (!modal) return;
  $("admin-create-user-error")?.classList.add("hidden");
  $("form-admin-create-user")?.reset();
  modal.classList.remove("hidden");
  $("admin-new-email")?.focus();
}

function closeCreateUserModal() {
  $("modal-create-user")?.classList.add("hidden");
}
