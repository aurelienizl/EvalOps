/** Exercise specifications, resources, evaluation history and environment actions. */
import { $, apiCall, cloneTemplate, formatDate, pollEnvironment, setOperationPending, showMessage, showToast, state } from "../core.js";
import { renderSafeMarkdown } from "../markdown.js";
import { updateButtonsLockState } from "../components/environment-banner.js";

let exerciseRequest = 0;
let historyRequest = 0;
let modalTrigger = null;

const exerciseContext = exerciseId => ({ exerciseId, user: state.user, routeVersion: state.routeVersion });
const isCurrentExercise = context => state.activeExerciseId === context.exerciseId &&
  state.user === context.user && state.routeVersion === context.routeVersion;
const exerciseEndpoint = exerciseId => `/api/v1/exercises/${encodeURIComponent(exerciseId)}`;

function resourceItem(resource, exerciseId) {
  const item = cloneTemplate("template-exercise-resource");
  item.querySelector("[data-resource-name]").textContent = resource.name;
  item.querySelector("[data-resource-download]").href = `${exerciseEndpoint(exerciseId)}/resources/${encodeURIComponent(resource.id)}`;
  return item;
}

export async function loadExerciseView(exerciseId) {
  state.activeExerciseId = exerciseId;
  state.exerciseAvailable = false;
  updateButtonsLockState();
  const context = exerciseContext(exerciseId);
  const request = ++exerciseRequest;
  historyRequest++;
  const readme = $("exercise-readme-content");
  const resources = $("exercise-resources-list");
  showMessage(readme, "Loading specifications...");
  showMessage(resources, "Loading attachments...", "text-muted mono empty-message");
  showMessage($("exercise-history-list"), "Loading audit logs...", "text-muted mono empty-message");
  for (const id of ["exercise-title", "exercise-diff-tag", "exercise-points-tag", "exercise-status-tag"]) {
    if ($(id)) $(id).textContent = "";
  }
  $("exercise-quota-tag")?.classList.add("hidden");

  try {
    const exercise = await apiCall(exerciseEndpoint(exerciseId));
    if (request !== exerciseRequest || !isCurrentExercise(context)) return;
    state.exerciseAvailable = exercise.available === true && !exercise.is_expired;
    updateButtonsLockState();
    const breadcrumb = $("exercise-breadcrumb-link");
    if (breadcrumb) {
      breadcrumb.href = `#courses/${encodeURIComponent(exercise.course_id)}`;
      breadcrumb.textContent = `← BACK TO MODULE: ${String(exercise.course_name).toUpperCase()}`;
    }
    $("exercise-title").textContent = exercise.name;
    const difficulty = $("exercise-diff-tag");
    difficulty.className = `tag tag-${exercise.difficulty}`;
    difficulty.textContent = String(exercise.difficulty).toUpperCase();
    $("exercise-points-tag").textContent = `${exercise.points} PTS`;
    const status = $("exercise-status-tag");
    status.textContent = exercise.available !== true ? "UNAVAILABLE" : exercise.is_expired ? "DEADLINE EXPIRED" : exercise.completed ? "PASSED ✓" : "NOT PASSED";
    status.className = exercise.completed ? "tag tag-status" : "tag";
    const quotaTag = $("exercise-quota-tag");
    if (quotaTag && exercise.evaluation_quota) {
      const quota = exercise.evaluation_quota;
      quotaTag.className = `tag ${quota.remaining === 0 ? "tag-quota-exhausted" : "tag-quota"}`;
      quotaTag.textContent = quota.remaining === 0
        ? `QUOTA EXHAUSTED // WAIT ${Math.ceil((quota.reset_in_seconds || 60) / 60)}M`
        : `QUOTA: ${quota.remaining}/${quota.max_evaluations} (${quota.window_minutes}M)`;
    }
    if (readme) readme.innerHTML = renderSafeMarkdown(exercise.readme);
    if (resources) {
      resources.replaceChildren(...exercise.resources.map(resource => resourceItem(resource, exerciseId)));
      if (!resources.children.length) showMessage(resources, "No attachments available.", "text-muted mono empty-message");
    }
    await loadEvaluationHistory(exerciseId);
  } catch (error) {
    if (request !== exerciseRequest || !isCurrentExercise(context)) return;
    showMessage(readme, error.message, "alert alert-error");
    resources?.replaceChildren();
    $("exercise-history-list")?.replaceChildren();
  }
}

function historyItem(evaluation, context) {
  const item = cloneTemplate("template-exercise-history");
  const isError = evaluation.status === "error" || evaluation.status === "interrupted";
  const isSuccess = evaluation.total > 0 && evaluation.passed === evaluation.total && evaluation.status === "completed";
  const status = item.querySelector("[data-history-status]");
  status.classList.add(`history-status-${isError ? "error" : isSuccess ? "success" : "warning"}`);
  status.textContent = isError ? "SYSTEM ERROR" : evaluation.status === "running" ? "IN PROGRESS" : `${evaluation.passed}/${evaluation.total} (${evaluation.percentage}%)${isSuccess ? " ✓" : ""}`;
  item.querySelector("[data-history-date]").textContent = formatDate(evaluation.created_at);
  item.querySelector("[data-history-meta]").textContent = isError
    ? evaluation.error_message || "Unknown error" : `${evaluation.tests.length} tests executed`;
  item.querySelector(".btn-snapshot-download").addEventListener("click", event => {
    event.stopPropagation();
    if (isCurrentExercise(context)) window.location.href = `/api/v1/evaluations/${encodeURIComponent(evaluation.id)}/snapshot`;
  });
  const openReport = () => { if (isCurrentExercise(context)) showEvaluationModal(evaluation); };
  item.addEventListener("click", openReport);
  item.addEventListener("keydown", event => {
    if (event.target === item && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      openReport();
    }
  });
  return item;
}

export async function loadEvaluationHistory(exerciseId) {
  const container = $("exercise-history-list");
  const context = exerciseContext(exerciseId);
  if (!container || !isCurrentExercise(context)) return;
  const request = ++historyRequest;
  showMessage(container, "Loading audit logs...", "text-muted mono empty-message");
  try {
    const data = await apiCall(`${exerciseEndpoint(exerciseId)}/evaluations?limit=10`);
    if (request !== historyRequest || !isCurrentExercise(context)) return;
    container.replaceChildren(...data.evaluations.map(evaluation => historyItem(evaluation, context)));
    if (!container.children.length) showMessage(container, "No evaluation records found.", "text-muted mono empty-message");
  } catch (error) {
    if (request === historyRequest && isCurrentExercise(context)) showMessage(container, error.message, "alert alert-error");
  }
}

function evaluationTest(test) {
  const item = cloneTemplate("template-evaluation-test");
  item.classList.add(test.passed ? "passed" : "failed");
  item.querySelector("[data-test-name]").textContent = test.name || test.id;
  const status = item.querySelector("[data-test-status]");
  status.classList.add(test.passed ? "tag-status" : "tag-hard");
  status.textContent = test.passed ? "PASS" : "FAIL";
  const message = item.querySelector("[data-test-message]");
  if (test.message) message.textContent = test.message;
  else message.remove();
  return item;
}

export function showEvaluationModal(evaluation) {
  const modal = $("modal-eval");
  const body = $("modal-eval-body");
  const title = $("modal-eval-title");
  if (!modal || !body || !title) return;
  title.textContent = `EVALUATION REPORT // ${formatDate(evaluation.created_at)}`;
  body.replaceChildren();
  if (evaluation.status === "error" || evaluation.status === "interrupted") {
    const error = cloneTemplate("template-evaluation-error");
    error.querySelector("[data-error-code]").textContent = evaluation.error_code || "EVALUATOR_ERROR";
    error.querySelector("[data-error-message]").textContent = evaluation.error_message || "Evaluation could not be completed.";
    body.append(error);
  } else if (evaluation.status === "running") {
    showMessage(body, "Evaluation is still in progress. Refresh the history to see the result.");
  } else {
    const isSuccess = evaluation.total > 0 && evaluation.passed === evaluation.total;
    const summary = cloneTemplate("template-evaluation-summary");
    summary.className = `alert ${isSuccess ? "alert-success" : "alert-warning"}`;
    summary.querySelector("[data-summary-score]").textContent = `SCORE // ${evaluation.passed} / ${evaluation.total} TESTS PASSED (${evaluation.percentage}%)`;
    summary.querySelector("[data-summary-detail]").textContent = isSuccess
      ? "Full validation. All test assertions passed." : "Partial validation or failed assertions detected.";
    const tests = document.createElement("div");
    tests.className = "report-tests";
    tests.append(...evaluation.tests.map(evaluationTest));
    body.append(summary, tests);
  }
  if (modal.classList.contains("hidden")) modalTrigger = document.activeElement;
  modal.classList.remove("hidden");
  $("modal-eval-close")?.focus();
}

function closeEvaluationModal() {
  const modal = $("modal-eval");
  if (!modal || modal.classList.contains("hidden")) return;
  modal.classList.add("hidden");
  if (modalTrigger?.isConnected && modalTrigger.getClientRects().length) modalTrigger.focus();
  modalTrigger = null;
}

async function performLockedAction(message, action) {
  if (state.user?.role !== "student" || state.isLocked) return;
  const user = state.user;
  setOperationPending(true);
  if (message) showToast(message);
  try {
    await action();
  } finally {
    if (state.user === user) {
      try { await pollEnvironment(true); }
      finally {
        if (state.user === user) {
          setOperationPending(false);
        }
      }
    }
  }
}

async function gradeExercise(context) {
  try {
    const result = await apiCall(`${exerciseEndpoint(context.exerciseId)}/grade`, { method: "POST" });
    if (state.user === context.user) showToast("Evaluation completed!");
    if (isCurrentExercise(context)) showEvaluationModal(result.evaluation);
  } catch (error) {
    if (state.user === context.user) showToast(`Evaluation error: ${error.message}`, 5000);
    if (error.details?.operation_id && isCurrentExercise(context)) {
      try {
        const evaluation = await apiCall(`/api/v1/evaluations/${encodeURIComponent(error.details.operation_id)}`);
        if (isCurrentExercise(context)) showEvaluationModal(evaluation);
      } catch { /* The original evaluation error was already reported. */ }
    }
  }
  if (isCurrentExercise(context)) await loadExerciseView(context.exerciseId);
}

export function initExerciseActions() {
  $("btn-start")?.addEventListener("click", () => {
    if (!state.user || !state.activeExerciseId || !state.exerciseAvailable || state.isLocked) return;
    const context = exerciseContext(state.activeExerciseId);
    performLockedAction("Starting environment...", async () => {
      try {
        await apiCall(`${exerciseEndpoint(context.exerciseId)}/start`, { method: "POST" });
        if (state.user === context.user) showToast("Environment ready!");
      } catch (error) {
        if (state.user === context.user) showToast(`Error: ${error.message}`, 5000);
      }
    });
  });
  const stopEnvironment = () => {
    if (!state.user || state.isLocked) return;
    const user = state.user;
    performLockedAction("Stopping environment...", async () => {
      try {
        await apiCall("/api/v1/environment/stop", { method: "POST" });
        if (state.user === user) showToast("Environment stopped.");
      } catch (error) {
        if (state.user === user) showToast(`Error: ${error.message}`);
      }
    });
  };
  $("btn-stop")?.addEventListener("click", stopEnvironment);
  $("banner-btn-stop")?.addEventListener("click", stopEnvironment);
  $("btn-grade")?.addEventListener("click", () => {
    if (!state.user || !state.activeExerciseId || !state.exerciseAvailable || state.isLocked) return;
    const context = exerciseContext(state.activeExerciseId);
    if (!window.confirm("Grading will stop your running environment. Saved workspace files are preserved. You can start it again afterwards.\n\nDo you want to proceed?")) return;
    performLockedAction("Evaluating submission...", () => gradeExercise(context));
  });
  $("banner-btn-copy")?.addEventListener("click", async () => {
    const command = $("banner-ssh-cmd")?.textContent;
    if (!command) return;
    try {
      await navigator.clipboard.writeText(command);
      showToast("SSH COMMAND COPIED");
    } catch { showToast("Unable to copy SSH command.", 5000); }
  });
  const modal = $("modal-eval");
  $("modal-eval-close")?.addEventListener("click", closeEvaluationModal);
  modal?.addEventListener("click", event => { if (event.target === modal) closeEvaluationModal(); });
  document.addEventListener("keydown", event => {
    if (!modal || modal.classList.contains("hidden")) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeEvaluationModal();
    } else if (event.key === "Tab") {
      event.preventDefault();
      $("modal-eval-close")?.focus();
    }
  });
}
