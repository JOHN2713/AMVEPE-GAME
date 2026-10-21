import { api, ApiError, store, withRetry } from "./api.js";

const IDLE_SECONDS = 90;
const $ = (id) => document.getElementById(id);

const sessionId = new URLSearchParams(window.location.search).get("s") || store.get("session")?.id;

function newPlayer() {
  store.clear();
  window.location.assign("/");
}

function render(result) {
  $("result-loading").hidden = true;
  $("result-error").hidden = true;
  $("result-content").hidden = false;
  $("result-name").textContent = result.first_name ? `${result.first_name} · ` : "";
  $("result-player").textContent = result.player;
  $("result-total").textContent = String(result.total_score);
  $("result-memory").textContent = String(result.memory_score);
  $("result-pairs").textContent = String(result.pairs_found);
  $("result-pairs-total").textContent = String(result.pairs_total);
  $("result-breed").textContent = String(result.breed_score);
  $("result-breed-correct").textContent = String(result.breed_correct);
  $("result-breed-answered").textContent = String(result.breed_answered);
  if (result.ranking) {
    $("result-position").hidden = false;
    $("result-position-number").textContent = `#${result.ranking.position}`;
    $("result-position-total").textContent = result.ranking.is_best
      ? `de ${result.ranking.total_players} ${result.ranking.total_players === 1 ? "jugador" : "jugadores"}`
      : `con tu mejor puntaje (${result.ranking.best_score})`;
  }
}

async function load() {
  if (!sessionId) {
    window.location.replace("/");
    return;
  }
  $("result-loading").hidden = false;
  $("result-error").hidden = true;
  try {
    render(await withRetry(() => api.result(sessionId)));
  } catch (err) {
    $("result-loading").hidden = true;
    $("result-error").hidden = false;
    $("result-error-text").textContent = err instanceof ApiError ? err.message : "Inténtalo de nuevo.";
  }
}

// Kiosco: si nadie interactúa, la pantalla vuelve sola al registro para el siguiente jugador.
let idleRemaining = IDLE_SECONDS;
function resetIdle() {
  idleRemaining = IDLE_SECONDS;
}
["pointermove", "pointerdown", "keydown", "wheel"].forEach((evt) => window.addEventListener(evt, resetIdle, { passive: true }));
setInterval(() => {
  idleRemaining -= 1;
  $("idle-notice").textContent = idleRemaining <= 30 ? `Volviendo al inicio en ${idleRemaining} s` : "";
  if (idleRemaining <= 0) newPlayer();
}, 1000);

$("new-player-btn").addEventListener("click", newPlayer);
$("result-retry").addEventListener("click", load);
load();
