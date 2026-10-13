import { $, apiCall, clearSession, setSession, showToast } from "../core.js";

export function initLoginForm() {
  const formLogin = $("form-login");
  formLogin.addEventListener("submit", async (e) => {
    e.preventDefault();
    const submit = $("login-submit");
    if (submit.disabled) return;
    submit.disabled = true;
    const email = $("login-email").value;
    const password = $("login-password").value;
    const errEl = $("login-error");
    errEl.classList.add("hidden");

    try {
      const data = await apiCall("/api/v1/auth/login", {
        method: "POST",
        body: { email, password },
      });
      setSession(data.student, data.csrf_token);
      $("login-password").value = "";
      window.location.hash = "#courses";
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove("hidden");
    } finally {
      submit.disabled = false;
    }
  });

  $("btn-logout")?.addEventListener("click", async () => {
    const button = $("btn-logout");
    if (button.disabled) return;
    button.disabled = true;
    try {
      await apiCall("/api/v1/auth/logout", { method: "POST" });
      clearSession();
    } catch (error) {
      if (error.status === 401) clearSession();
      else showToast(`Error: ${error.message}`, 5000);
    } finally {
      button.disabled = false;
    }
  });
}
