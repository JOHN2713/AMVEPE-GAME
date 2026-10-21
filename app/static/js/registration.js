import { api, ApiError, store } from "./api.js";
import { MESSAGES, validateEmail, validateName, validatePhone } from "./validation.js";

const form = document.getElementById("registration-form");
const submitBtn = document.getElementById("submit-btn");
const summary = document.getElementById("error-summary");

const FIELD_LABELS = {
  full_name: "Nombre completo",
  email: "Correo electrónico",
  phone: "Celular",
  accept_terms: "Términos y Condiciones",
  accept_privacy: "Aviso de Privacidad",
};

const validators = {
  full_name: () => validateName(form.full_name.value),
  email: () => validateEmail(form.email.value),
  phone: () => validatePhone(form.phone.value),
  accept_terms: () => (form.accept_terms.checked ? null : MESSAGES.terms),
  accept_privacy: () => (form.accept_privacy.checked ? null : MESSAGES.privacy),
};

// Un participante nuevo empieza siempre con el estado del kiosco limpio.
store.clear();

function setFieldError(name, message) {
  const input = form.elements[name];
  const errorEl = document.getElementById(`${name}-error`);
  if (message) {
    input.setAttribute("aria-invalid", "true");
    errorEl.innerHTML = `<svg class="h-5 w-5 shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-.75-11.5a.75.75 0 011.5 0v4a.75.75 0 01-1.5 0v-4zM10 15a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd"/></svg>`;
    errorEl.append(document.createTextNode(message));
    errorEl.hidden = false;
  } else {
    input.removeAttribute("aria-invalid");
    errorEl.textContent = "";
    errorEl.hidden = true;
  }
}

function showSummary(errors, message) {
  const entries = Object.entries(errors);
  if (!entries.length && !message) {
    summary.hidden = true;
    return;
  }
  summary.replaceChildren();
  const title = document.createElement("p");
  title.textContent = message || "Revisa los datos marcados:";
  summary.append(title);
  if (entries.length > 1) {
    // Resumen corto en pantalla; el detalle completo queda para lectores de pantalla.
    title.textContent = `${message || "Revisa los datos marcados"}: ${entries.length} campos por corregir.`;
    const list = document.createElement("ul");
    list.className = "sr-only";
    for (const [name, msg] of entries) {
      const li = document.createElement("li");
      li.textContent = `${FIELD_LABELS[name] ?? name}: ${msg}`;
      list.append(li);
    }
    summary.append(list);
  }
  summary.hidden = false;
}

function validateAll() {
  const errors = {};
  for (const [name, check] of Object.entries(validators)) {
    const msg = check();
    setFieldError(name, msg);
    if (msg) errors[name] = msg;
  }
  return errors;
}

// Validación inmediata al salir de cada campo y limpieza del error al corregir.
for (const name of Object.keys(validators)) {
  const input = form.elements[name];
  const event = input.type === "checkbox" ? "change" : "blur";
  input.addEventListener(event, () => setFieldError(name, validators[name]()));
  if (input.type !== "checkbox") {
    input.addEventListener("input", () => {
      if (input.getAttribute("aria-invalid") === "true" && !validators[name]()) setFieldError(name, null);
    });
  }
}

function setBusy(busy) {
  submitBtn.disabled = busy;
  submitBtn.querySelector("[data-label]").textContent = busy ? "Registrando…" : "Registrarme y jugar";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (submitBtn.disabled) return;

  const errors = validateAll();
  if (Object.keys(errors).length) {
    showSummary(errors);
    form.elements[Object.keys(errors)[0]].focus();
    return;
  }
  showSummary({});
  setBusy(true);
  try {
    const result = await api.register({
      full_name: form.full_name.value,
      email: form.email.value,
      phone: form.phone.value,
      accept_terms: form.accept_terms.checked,
      accept_privacy: form.accept_privacy.checked,
      marketing_opt_in: form.marketing_opt_in.checked,
      terms_version: form.dataset.termsVersion,
      privacy_version: form.dataset.privacyVersion,
    });
    store.set("participant", { id: result.participant_id, firstName: result.first_name, player: result.player });
    window.location.assign("/juego");
  } catch (err) {
    // Los datos del formulario se conservan para reintentar.
    setBusy(false);
    if (err instanceof ApiError && Object.keys(err.fields).length) {
      for (const [name, msg] of Object.entries(err.fields)) if (validators[name]) setFieldError(name, msg);
      showSummary(err.fields, err.message);
    } else {
      showSummary({}, err.message);
    }
    summary.focus();
  }
});

// ---------------------------------------------------------------- modales legales
document.querySelectorAll("[data-open-legal]").forEach((btn) => {
  btn.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    document.getElementById(`legal-${btn.dataset.openLegal}`).showModal();
  });
});
document.querySelectorAll("[data-close-legal]").forEach((btn) => {
  btn.addEventListener("click", () => btn.closest("dialog").close());
});
document.querySelectorAll("dialog.legal").forEach((dialog) => {
  // Clic fuera del contenido cierra el modal (el backdrop pertenece al propio <dialog>).
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
});
