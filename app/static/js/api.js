// Cliente HTTP de la API REST. Los errores de red se distinguen de los errores de negocio del servidor.

export class ApiError extends Error {
  constructor(message, { status = 0, code = "network_error", fields = {}, extra = {} } = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields;
    this.extra = extra;
  }
  get isNetwork() {
    return this.status === 0 || this.status >= 500 || this.status === 429;
  }
}

const NETWORK_MESSAGE = "No hay conexión con el servidor. Revisa la red e inténtalo de nuevo.";

export async function request(method, url, body, { timeoutMs = 10000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json", Accept: "application/json" } : { Accept: "application/json" },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(NETWORK_MESSAGE);
  } finally {
    clearTimeout(timer);
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    const err = data?.error ?? {};
    const { code, message, fields, ...extra } = err;
    throw new ApiError(message || NETWORK_MESSAGE, { status: response.status, code: code || `http_${response.status}`, fields: fields || {}, extra });
  }
  return data;
}

/** Reintenta solo fallas de red/servidor, con espera creciente. Útil para acciones idempotentes. */
export async function withRetry(fn, { attempts = 4, baseDelayMs = 400, onRetry } = {}) {
  let lastError;
  for (let i = 0; i < attempts; i += 1) {
    try {
      return await fn();
    } catch (err) {
      lastError = err;
      if (!(err instanceof ApiError) || !err.isNetwork || i === attempts - 1) throw err;
      onRetry?.(err, i + 1);
      await new Promise((r) => setTimeout(r, baseDelayMs * 2 ** i));
    }
  }
  throw lastError;
}

export const api = {
  register: (payload) => request("POST", "/api/registrations", payload),
  createSession: (participantId) => request("POST", "/api/game/sessions", { participant_id: participantId }),
  getSession: (id) => request("GET", `/api/game/sessions/${id}`),
  start: (id) => request("POST", `/api/game/sessions/${id}/start`, {}),
  memoryMatch: (id, a, b) => request("POST", `/api/game/sessions/${id}/memory-match`, { cards: [a, b] }),
  breedQuestion: (id) => request("GET", `/api/game/sessions/${id}/breed-question`),
  breedAnswer: (id, questionToken, optionId) =>
    request("POST", `/api/game/sessions/${id}/breed-answer`, { question_token: questionToken, option_id: optionId }),
  finish: (id) => request("POST", `/api/game/sessions/${id}/finish`, {}),
  result: (id) => request("GET", `/api/game/sessions/${id}/result`),
  ranking: (limit = 10) => request("GET", `/api/ranking?limit=${limit}`),
};

// Estado del kiosco entre pantallas (se borra al pulsar "Nuevo jugador").
export const store = {
  get(key) {
    try {
      return JSON.parse(sessionStorage.getItem(`pp.${key}`));
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      sessionStorage.setItem(`pp.${key}`, JSON.stringify(value));
    } catch {
      /* almacenamiento no disponible: el flujo sigue en memoria */
    }
  },
  clear() {
    try {
      ["participant", "session"].forEach((k) => sessionStorage.removeItem(`pp.${k}`));
    } catch {
      /* sin almacenamiento */
    }
  },
};
