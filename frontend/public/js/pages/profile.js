import { $, apiCall, clearSession, showToast, state } from "../core.js";

function showFeedback(id, message, success = false) {
  const feedback = $(id);
  feedback.className = `alert alert-${success ? "success" : "error"}`;
  feedback.textContent = message;
}

export async function loadProfileView() {
  const sshArea = $("profile-ssh-key");
  const user = state.user;
  const version = state.routeVersion;
  $("ssh-key-feedback").className = "feedback-msg hidden";
  $("password-feedback").className = "feedback-msg hidden";
  sshArea.value = "";
  try {
    const prof = await apiCall("/api/v1/profile");
    if (user === state.user && version === state.routeVersion && !sshArea.value) sshArea.value = prof.ssh_public_key || "";
  } catch (err) {
    if (user === state.user && version === state.routeVersion) showToast(err.message);
  }
}

export function initProfileForms() {
  $("form-ssh-key").addEventListener("submit", async event => {
    event.preventDefault();
    const button = $("btn-save-ssh-key");
    if (!state.user || state.isLocked || button.dataset.pending !== undefined) return;
    const user = state.user;
    const pending = String(state.sessionVersion);
    button.dataset.pending = pending;
    button.disabled = true;
    $("ssh-key-feedback").classList.add("hidden");
    try {
      await apiCall("/api/v1/profile/ssh-key", {
        method: "PUT", body: { public_key: $("profile-ssh-key").value },
      });
      if (user === state.user) showFeedback("ssh-key-feedback", "SSH key saved successfully!", true);
    } catch (error) {
      if (user === state.user) showFeedback("ssh-key-feedback", error.message);
    } finally {
      if (button.dataset.pending === pending) {
        delete button.dataset.pending;
        button.disabled = state.isLocked;
      }
    }
  });

  $("form-password").addEventListener("submit", async event => {
    event.preventDefault();
    const button = $("btn-save-password");
    if (!state.user || button.disabled) return;
    const password = $("pwd-new").value;
    if (password !== $("pwd-confirm").value) {
      showFeedback("password-feedback", "New passwords do not match");
      return;
    }
    const user = state.user;
    const pending = String(state.sessionVersion);
    button.dataset.pending = pending;
    button.disabled = true;
    $("password-feedback").classList.add("hidden");
    try {
      await apiCall("/api/v1/profile/password", {
        method: "PUT", body: { current_password: $("pwd-current").value, new_password: password },
      });
      if (user === state.user) {
        showToast("Password updated. Please sign in again.");
        clearSession();
      }
    } catch (error) {
      if (user === state.user) showFeedback("password-feedback", error.message);
    } finally {
      if (button.dataset.pending === pending) {
        delete button.dataset.pending;
        button.disabled = false;
      }
    }
  });
}
