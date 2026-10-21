// Etapa 1: tablero de 12 cartas. El servidor decide si dos cartas son pareja; el navegador solo muestra.
import { ApiError } from "./api.js";

const MISMATCH_DELAY_MS = 750;
const BACK_ICON = `
  <svg viewBox="0 0 64 64" class="h-1/2 w-1/2 text-white" fill="currentColor" aria-hidden="true">
    <ellipse cx="18" cy="24" rx="6" ry="8"/><ellipse cx="46" cy="24" rx="6" ry="8"/>
    <ellipse cx="9" cy="38" rx="5" ry="7"/><ellipse cx="55" cy="38" rx="5" ry="7"/>
    <path d="M32 32c-9 0-17 10-17 17 0 5 4 7 8 7 4 0 6-2 9-2s5 2 9 2c4 0 8-2 8-7 0-7-8-17-17-17z"/>
  </svg>`;

export class MemoryGame {
  constructor({ board, api, sessionId, onScore, onPairsChange, onComplete, onError }) {
    this.board = board;
    this.api = api;
    this.sessionId = sessionId;
    this.onScore = onScore;
    this.onPairsChange = onPairsChange;
    this.onComplete = onComplete;
    this.onError = onError;
    this.cards = new Map();
    this.selection = [];
    this.busy = false;
    this.locked = false;
  }

  render(cards) {
    this.board.replaceChildren();
    cards.forEach((card, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "memory-card";
      button.dataset.token = card.token;
      button.setAttribute("aria-label", `Carta ${index + 1}, boca abajo`);
      button.innerHTML = `
        <span class="memory-card-inner">
          <span class="memory-face memory-back">${BACK_ICON}</span>
          <span class="memory-face memory-front">
            <img src="${card.image_url}" alt="" class="h-full w-full object-cover" draggable="false">
            <span class="memory-badge bg-correct" hidden aria-hidden="true">✓</span>
          </span>
        </span>`;
      button.addEventListener("click", () => this.flip(card.token));
      this.board.append(button);
      this.cards.set(card.token, { el: button, index, matched: card.matched });
      if (card.matched) this.markMatched(card.token);
    });
  }

  get pairsFound() {
    return [...this.cards.values()].filter((c) => c.matched).length / 2;
  }

  setFaceUp(token, faceUp) {
    const card = this.cards.get(token);
    card.el.classList.toggle("is-flipped", faceUp);
    card.el.setAttribute("aria-label", `Carta ${card.index + 1}, ${faceUp ? "boca arriba" : "boca abajo"}`);
  }

  markMatched(token) {
    const card = this.cards.get(token);
    card.matched = true;
    card.el.classList.add("is-matched");
    card.el.classList.remove("is-flipped", "is-wrong");
    card.el.disabled = true;
    card.el.querySelector(".memory-badge").hidden = false;
    card.el.setAttribute("aria-label", `Carta ${card.index + 1}, pareja encontrada`);
  }

  async flip(token) {
    const card = this.cards.get(token);
    if (this.locked || this.busy || card.matched || this.selection.includes(token)) return;
    this.setFaceUp(token, true);
    this.selection.push(token);
    if (this.selection.length < 2) return;

    const [a, b] = this.selection;
    this.busy = true;
    const flippedAt = performance.now();
    try {
      const result = await this.api.memoryMatch(this.sessionId, a, b);
      if (result.match) {
        this.markMatched(a);
        this.markMatched(b);
        this.onScore?.(result.total_score, result.points_awarded);
        this.onPairsChange?.(result.pairs_found, result.pairs_total);
        if (result.memory_complete) {
          // Breve pausa para que se vea la última pareja antes de pasar a la etapa 2.
          setTimeout(() => this.onComplete?.(result.memory_end_ms), 600);
        }
      } else {
        this.cards.get(a).el.classList.add("is-wrong");
        this.cards.get(b).el.classList.add("is-wrong");
        const wait = Math.max(0, MISMATCH_DELAY_MS - (performance.now() - flippedAt));
        await new Promise((r) => setTimeout(r, wait));
        this.hide(a);
        this.hide(b);
      }
    } catch (err) {
      this.hide(a);
      this.hide(b);
      // Fin de la etapa según el servidor: se bloquea el tablero sin sumar puntos.
      if (err instanceof ApiError && err.code === "memory_stage_closed") this.lock();
      else this.onError?.(err);
    } finally {
      this.selection = [];
      this.busy = false;
    }
  }

  hide(token) {
    const card = this.cards.get(token);
    if (card.matched) return;
    card.el.classList.remove("is-wrong");
    this.setFaceUp(token, false);
  }

  /** Cierra la etapa: una carta levantada sin pareja no suma y vuelve a ocultarse. */
  lock() {
    this.locked = true;
    for (const token of this.selection) this.hide(token);
    for (const card of this.cards.values()) card.el.disabled = true;
  }
}
