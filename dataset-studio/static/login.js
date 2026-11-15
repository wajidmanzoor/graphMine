"use strict";
/* Sign-in page: posts the credentials; the server answers with a session cookie. */
const form = document.getElementById("login-form");
const error = document.getElementById("login-error");
const button = form.querySelector("button[type=submit]");

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  error.hidden = true;
  button.disabled = true;
  button.textContent = "Signing in…";
  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: form.username.value, password: form.password.value }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Sign-in failed");
    location.replace("/");
  } catch (err) {
    error.textContent = err.message;
    error.hidden = false;
    form.password.value = "";
    form.password.focus();
  } finally {
    button.disabled = false;
    button.textContent = "Sign in";
  }
});
