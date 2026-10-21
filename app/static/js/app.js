// Orquestador de la pantalla de juego: prepara la sesión, precarga imágenes, sincroniza el reloj
// con el servidor y cambia de etapa automáticamente (45 s + 45 s, sin pausas).
import { api, ApiError, store, withRetry } from "./api.js";
import { BreedGame } from "./breed-game.js";
import { MemoryGame } from "./memory-game.js";
import { formatTime, GameClock } from "./timer.js";

const $ = (id) => document.getElementById(id);
const ui = {
  overlay: $("overlay"),
  overlayTitle: $("overlay-title"),
  overlayText: $("overlay-text"),
  overlayCount: $("overlay-count"),
  overlayActions: $("overlay-actions"),
  timer: $("timer"),
  score: $("score"),
  scorePop: $("score-pop"),
  stageNumber: $("stage-number"),
  stageName: $("stage-name"),
  bars: [$("bar-stage-1"), $("bar-stage-2")],
  memoryStage: $("memory-stage"),
  breedStage: $("breed-stage"),
  pairsProgress: $("pairs-progress"),
  memoryHint: $("memory-hint"),
  stageBanner: $("stage-banner"),
  stageBannerText: $("stage-banner-text"),
  connection: $("connection-banner"),
};

const participant = store.get("participant");
let session = null;
let clock = null;
let memory = null;
let breed = null;
let currentStage = null;
let ticker = null;
let prefetchRequested = false;
let finishing = false;

// ---------------------------------------------------------------- overlay

function showOverlay(title, text = "", { count = null, actions = false } = {}) {
  ui.overlay.hidden = false;
  ui.overlayTitle.textContent = title;
  ui.overlayText.textContent = text;
  ui.overlayText.hidden = !text;
  ui.overlayCount.hidden = count === null;
  if (count !== null) ui.overlayCount.textContent = String(count);
  ui.overlayActions.hidden = !actions;
}

function hideOverlay() {
  ui.overlay.hidden = true;
}

function fatal(message) {
  stopTicker();
  showOverlay("No pudimos continuar", message, { actions: true });
}

let connectionTimer = null;
function flagConnection(err) {
  if (err instanceof ApiError && !err.isNetwork) return;
  ui.connection.hidden = false;
  clearTimeout(connectionTimer);
  connectionTimer = setTimeout(() => (ui.connection.hidden = true), 3000);
}

// ---------------------------------------------------------------- marcador

function setScore(total, gained = 0) {
  ui.score.textContent = String(total);
  if (gained > 0) {
    ui.scorePop.textContent = `+${gained}`;
    ui.scorePop.hidden = false;
    ui.scorePop.classList.remove("animate-float-up");
    void ui.scorePop.offsetWidth; // reinicia la animación
    ui.scorePop.classList.add("animate-float-up");
  }
}

function setPairs(found, total) {
  ui.pairsProgress.textContent = String(found);
}

/** Tablero completo antes de los 45 s: la etapa 2 empieza ya y hereda el tiempo sobrante. */
function onMemoryComplete(memoryEndMs) {
  clock.setMemoryEnd(memoryEndMs);
  const saved = Math.max(0, Math.round((clock.stageMs - clock.memoryEndMs) / 1000));
  ui.stageBannerText.textContent = saved > 0 ? `¡Tablero completo! +${saved} s para las razas` : "¡Etapa 2! ¿Qué raza es?";
  tick();
}

// ---------------------------------------------------------------- precarga

function preloadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => (img.decode ? img.decode().catch(() => {}).then(resolve) : resolve());
    img.onerror = () => reject(new Error(url));
    img.src = url;
  });
}

async function preloadAll(urls) {
  let done = 0;
  const update = () => (ui.overlayText.textContent = `Cargando imágenes ${done}/${urls.length}`);
  update();
  const load = async (url) => {
    try {
      await preloadImage(url);
    } catch {
      await preloadImage(url); // un reintento
    }
    done += 1;
    update();
  };
  await Promise.all(urls.map(load));
}

// ---------------------------------------------------------------- reloj y etapas

function stopTicker() {
  if (ticker) clearInterval(ticker);
  ticker = null;
}

function tick() {
  const remaining = clock.remainingMs;
  ui.timer.textContent = formatTime(remaining);
  clock.stageProgress().forEach((fraction, i) => {
    ui.bars[i].firstElementChild.style.width = `${(1 - fraction) * 100}%`;
  });
  const stage = clock.stage;
  const stageRemaining = stage === "memory" ? clock.memoryEndMs - clock.elapsedMs : remaining;
  ui.bars.forEach((bar) => bar.classList.toggle("is-low", stageRemaining < 10000));

  if (stage === "memory" && !prefetchRequested && clock.elapsedMs > clock.memoryEndMs - 1200) {
    prefetchRequested = true;
    breed.prefetch();
  }
  if (stage !== currentStage) enterStage(stage);
}

function enterStage(stage) {
  const previous = currentStage;
  currentStage = stage;
  if (stage === "memory") {
    ui.stageNumber.textContent = "1";
    ui.stageName.textContent = "Memoria animal";
    ui.memoryStage.hidden = false;
    ui.breedStage.hidden = true;
  } else if (stage === "breed") {
    memory.lock();
    ui.stageNumber.textContent = "2";
    ui.stageName.textContent = "¿Qué raza es?";
    ui.memoryStage.hidden = true;
    ui.breedStage.hidden = false;
    if (previous === "memory") {
      ui.stageBanner.hidden = false;
      setTimeout(() => (ui.stageBanner.hidden = true), 1800);
    }
    breed.begin(session.breed_correct ?? 0);
  } else if (stage === "finished") {
    finish();
  }
}

async function finish() {
  if (finishing) return;
  finishing = true;
  stopTicker();
  memory?.lock();
  breed?.lock();
  ui.timer.textContent = "0:00";
  showOverlay("¡Tiempo!", "Calculando tu resultado…");
  for (let attempt = 0; attempt < 8; attempt += 1) {
    try {
      await withRetry(() => api.finish(session.session_id), { onRetry: flagConnection });
      window.location.assign(`/resultados?s=${encodeURIComponent(session.session_id)}`);
      return;
    } catch (err) {
      if (err instanceof ApiError && err.code === "session_in_progress") {
        // El reloj local se adelantó unos milisegundos al del servidor.
        await new Promise((r) => setTimeout(r, (err.extra.remaining_ms ?? 300) + 150));
        continue;
      }
      fatal(err.message);
      return;
    }
  }
  fatal("El servidor no confirmó el final de la partida.");
}

// ---------------------------------------------------------------- arranque

async function countdown() {
  for (const n of [3, 2, 1]) {
    showOverlay("¡Prepárate!", "Encuentra las parejas de animales", { count: n });
    await new Promise((r) => setTimeout(r, 800));
  }
}

function buildGames() {
  memory = new MemoryGame({
    board: $("memory-board"),
    api,
    sessionId: session.session_id,
    onScore: setScore,
    onPairsChange: setPairs,
    onComplete: onMemoryComplete,
    onError: flagConnection,
  });
  breed = new BreedGame({
    api,
    sessionId: session.session_id,
    elements: {
      image: $("breed-image"),
      optionsWrap: $("breed-options"),
      feedback: $("breed-feedback"),
      number: $("question-number"),
      progress: $("breed-progress"),
      exhausted: $("breed-exhausted"),
      panels: [$("breed-image-panel"), $("breed-question-panel")],
    },
    onScore: setScore,
    onError: flagConnection,
  });
  memory.render(session.cards);
  setScore(session.total_score);
  setPairs(session.pairs_found, session.pairs_total);
}

async function loadOrCreateSession() {
  const saved = store.get("session");
  if (saved?.id) {
    try {
      const state = await withRetry(() => api.getSession(saved.id));
      if (state.status === "created" || state.status === "in_progress") return state;
      if (["completed", "expired"].includes(state.status) || state.stage === "finished") {
        window.location.replace(`/resultados?s=${encodeURIComponent(saved.id)}`);
        return null;
      }
    } catch {
      /* sesión inválida: se crea otra */
    }
  }
  const state = await withRetry(() => api.createSession(participant.id));
  store.set("session", { id: state.session_id });
  return state;
}

async function main() {
  if (!participant?.id) {
    window.location.replace("/");
    return;
  }
  showOverlay("Preparando el tablero…", "Cargando imágenes");
  try {
    session = await loadOrCreateSession();
    if (!session) return;
    await preloadAll([...session.cards.map((c) => c.image_url), ...session.preload]);
  } catch (err) {
    if (err instanceof ApiError && err.code === "participant_not_found") {
      store.clear();
      window.location.replace("/");
      return;
    }
    fatal(err instanceof ApiError ? err.message : "No se pudieron cargar las imágenes. Avisa al asesor.");
    return;
  }

  clock = new GameClock({ stageSeconds: session.stage_seconds, totalSeconds: session.total_seconds });
  buildGames();

  try {
    if (session.status === "created") {
      await countdown();
      const sent = performance.now();
      session = { ...session, ...(await withRetry(() => api.start(session.session_id), { onRetry: flagConnection })) };
      clock.sync(session.elapsed_ms, performance.now() - sent);
    } else {
      // Recarga accidental: el tiempo sigue corriendo según el servidor.
      const sent = performance.now();
      const fresh = await withRetry(() => api.getSession(session.session_id));
      session = { ...session, ...fresh };
      clock.sync(fresh.elapsed_ms, performance.now() - sent);
    }
  } catch (err) {
    fatal(err.message);
    return;
  }

  clock.setMemoryEnd(session.memory_end_ms);
  hideOverlay();
  tick();
  ticker = setInterval(tick, 100);
}

$("retry-btn").addEventListener("click", () => window.location.reload());
$("home-link").addEventListener("click", () => store.clear());

main();
