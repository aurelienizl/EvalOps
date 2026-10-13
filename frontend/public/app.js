import { $, apiCall, pollEnvironment, setSession, state } from "./js/core.js";
import { updateButtonsLockState, updateRuntimeBanner } from "./js/components/environment-banner.js";
import { initLoginForm } from "./js/pages/login.js";
import { loadCoursesView } from "./js/pages/home.js";
import { loadCourseDetailView } from "./js/pages/course.js";
import { initExerciseActions, loadExerciseView } from "./js/pages/exercise.js";
import { initProfileForms, loadProfileView } from "./js/pages/profile.js";
import { loadAdminView } from "./js/pages/admin.js";

let sessionRequest = null;

function switchView(viewId) {
  document.querySelectorAll(".main-content > .view").forEach(view => {
    view.classList.toggle("hidden", view.id !== viewId);
  });
}

async function router() {
  const version = ++state.routeVersion;
  const hash = window.location.hash || "#courses";
  if (!state.user && hash !== "#login") {
    try {
      if (!sessionRequest) {
        const sessionVersion = state.sessionVersion;
        const request = apiCall("/api/v1/auth/me").then(user => {
          if (sessionVersion === state.sessionVersion && !state.user) setSession(user, user.csrf_token);
        }).finally(() => { if (sessionRequest === request) sessionRequest = null; });
        sessionRequest = request;
      }
      await sessionRequest;
    } catch {
      if (version === state.routeVersion && !state.user) window.location.hash = "#login";
      return;
    }
  }
  if (version !== state.routeVersion) return;
  if (!state.user && hash !== "#login") { window.location.hash = "#login"; return; }
  state.activeExerciseId = null;
  state.exerciseAvailable = false;
  updateButtonsLockState();
  let routeId;
  try { routeId = decodeURIComponent(hash.slice(hash.indexOf("/") + 1)); }
  catch { window.location.hash = "#courses"; return; }

  if (hash === "#login") {
    if (state.user) { window.location.hash = "#courses"; return; }
    switchView("view-login");
  } else if (hash === "#courses") {
    switchView("view-courses");
    await loadCoursesView();
  } else if (hash.startsWith("#courses/") && hash.length > 9) {
    switchView("view-course-detail");
    await loadCourseDetailView(routeId);
  } else if (hash.startsWith("#exercises/") && hash.length > 11) {
    switchView("view-exercise");
    await loadExerciseView(routeId);
  } else if (hash === "#profile") {
    switchView("view-profile");
    await loadProfileView();
  } else if (hash === "#admin" || hash.startsWith("#admin/")) {
    if (state.user?.role !== "admin") {
      window.location.hash = "#courses";
      return;
    }
    switchView("view-admin");
    await loadAdminView();
  } else {
    window.location.hash = "#courses";
  }
}

document.addEventListener("sessionchange", () => {
  sessionRequest = null;
  $("app-nav").classList.toggle("hidden", !state.user);
  $("user-email-display").textContent = state.user?.email || "";
  
  const isAdmin = state.user?.role === "admin";
  $("nav-admin")?.classList.toggle("hidden", !isAdmin);
  $("user-role-badge")?.classList.toggle("hidden", !isAdmin);

  if (state.user) {
    pollEnvironment();
    if (window.location.hash === "#login") window.location.hash = "#courses";
  } else {
    $("modal-eval").classList.add("hidden");
    $("modal-create-user")?.classList.add("hidden");
    for (const id of ["btn-save-ssh-key", "btn-save-password"]) {
      delete $(id).dataset.pending;
      $(id).disabled = false;
    }
    $("form-password").reset();
    $("profile-ssh-key").value = "";
    window.location.hash = "#login";
  }
});

document.addEventListener("environmentchange", () => updateRuntimeBanner(state.environment));
window.addEventListener("hashchange", router);
initLoginForm();
initExerciseActions();
initProfileForms();
updateRuntimeBanner(null);
router();
