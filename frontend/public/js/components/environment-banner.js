import { $, state } from "../core.js";

export function updateButtonsLockState() {
  const isStudent = state.user?.role === "student";
  ["btn-start", "btn-grade", "btn-stop", "btn-save-ssh-key"].forEach(id => {
    const button = $(id);
    const needsExercise = id === "btn-start" || id === "btn-grade";
    const canStop = ["running", "unknown"].includes(state.environment?.state);
    button.disabled = !state.user || state.isLocked || button.dataset.pending !== undefined ||
      (needsExercise && (!state.activeExerciseId || !state.exerciseAvailable)) ||
      ((needsExercise || id === "btn-stop") && !isStudent) || (id === "btn-stop" && !canStop);
  });
  $("banner-btn-stop").disabled = !isStudent || state.isLocked || !["running", "unknown"].includes(state.environment?.state);
  const notice = $("operation-notice");
  notice.textContent = "OPERATION IN PROGRESS: Actions on the environment are temporarily locked.";
  notice.classList.toggle("hidden", !state.isLocked);
}

export function updateRuntimeBanner(env) {
  const banner = $("global-runtime-banner");
  const statusText = $("banner-status-text");
  const exName = $("banner-exercise-name");
  const sshCmd = $("banner-ssh-cmd");
  const sshContainer = $("banner-ssh-container");
  updateButtonsLockState();

  if (!env || env.state === "stopped") {
    banner.classList.add("hidden");
    sshCmd.textContent = "";
    exName.textContent = "";
    return;
  }

  banner.classList.remove("hidden", "grading", "starting", "stopping", "running");
  banner.classList.add(env.state);

  const isRunning = env.state === "running";
  const stateLabels = {
    running: "ACTIVE ENVIRONMENT",
    starting: "INITIALIZING CONTAINER...",
    stopping: "STOPPING CONTAINER...",
    grading: "EVALUATING / RUNNING TESTS...",
    unknown: "ENVIRONMENT STATUS UNAVAILABLE",
  };

  statusText.textContent = stateLabels[env.state] || "OPERATION IN PROGRESS...";
  exName.textContent = isRunning && env.exercise ? `// ${env.exercise.name.toUpperCase()}` : "";

  if (isRunning && env.ssh) {
    sshContainer.classList.remove("hidden");
    sshCmd.textContent = `ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p ${env.ssh.port} ${env.ssh.user}@${env.ssh.host}`;
  } else {
    sshContainer.classList.add("hidden");
  }
}
