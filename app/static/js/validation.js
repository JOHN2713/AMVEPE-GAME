// Validaciones del formulario. Deben coincidir con app/services/validation.py (el servidor las repite).

export const MESSAGES = {
  nameRequired: "Ingresa tu nombre completo",
  nameLength: "El nombre debe tener entre 2 y 100 caracteres",
  nameChars: "El nombre solo puede contener letras, espacios, apóstrofes y guiones",
  email: "Ingresa un correo electrónico válido",
  phone: "Ingresa un celular ecuatoriano válido, por ejemplo 0991234567 o +593991234567",
  terms: "Debes aceptar los Términos y Condiciones para participar",
  privacy: "Debes autorizar el tratamiento de datos para registrar tu participación",
};

const NAME_RE = /^[\p{L}\p{M}' ’-]+$/u;
const HAS_LETTER_RE = /\p{L}/u;
// Formato práctico: local@dominio.tld sin espacios. El servidor hace la validación completa.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export function validateName(raw) {
  const value = (raw || "").normalize("NFC").trim().replace(/\s+/g, " ");
  if (!value) return MESSAGES.nameRequired;
  if (value.length < 2 || value.length > 100) return MESSAGES.nameLength;
  if (!NAME_RE.test(value) || !HAS_LETTER_RE.test(value)) return MESSAGES.nameChars;
  return null;
}

export function validateEmail(raw) {
  const value = (raw || "").trim();
  if (!value || value.length > 254 || !EMAIL_RE.test(value)) return MESSAGES.email;
  return null;
}

export function normalizePhone(raw) {
  const value = (raw || "").trim().replace(/[\s\-().]/g, "");
  if (/^09\d{8}$/.test(value)) return `+593${value.slice(1)}`;
  if (/^\+5939\d{8}$/.test(value)) return value;
  return null;
}

export function validatePhone(raw) {
  return normalizePhone(raw) ? null : MESSAGES.phone;
}
