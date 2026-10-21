// Etapa 2: una foto y tres opciones. La respuesta correcta solo la conoce el servidor.
import { ApiError } from "./api.js";

const FEEDBACK_MS = 900;
const CHECK = `<svg class="h-8 w-8 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" aria-hidden="true"><path d="M5 13l4 4L19 7" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const CROSS = `<svg class="h-8 w-8 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" stroke-linecap="round"/></svg>`;

export class BreedGame {
  constructor({ api, sessionId, elements, onScore, onError }) {
    this.api = api;
    this.sessionId = sessionId;
    this.el = elements;
    this.onScore = onScore;
    this.onError = onError;
    this.question = null;
    this.prefetched = null;
    this.answering = false;
    this.locked = false;
    this.correct = 0;
  }

  /** Pide la primera pregunta un instante antes del cambio de etapa para mostrarla sin espera. */
  async prefetch() {
    if (this.prefetched || this.prefetching) return;
    this.prefetching = this.api
      .breedQuestion(this.sessionId)
      .then((data) => {
        this.prefetched = data;
      })
      .catch(() => {
        this.prefetching = null;
      });
    await this.prefetching;
  }

  async begin(initialCorrect = 0) {
    this.correct = initialCorrect;
    this.el.progress.textContent = String(this.correct);
    if (!this.prefetched) {
      try {
        await this.prefetch();
        if (!this.prefetched) this.prefetched = await this.api.breedQuestion(this.sessionId);
      } catch (err) {
        this.onError?.(err);
        return;
      }
    }
    this.show(this.prefetched.question);
  }

  show(question) {
    if (this.locked) return;
    this.question = question;
    this.el.feedback.replaceChildren();
    if (!question) {
      this.el.exhausted.hidden = false;
      this.el.panels.forEach((panel) => (panel.hidden = true));
      return;
    }
    this.el.number.textContent = String(question.number);
    this.el.image.src = question.image_url;
    this.el.optionsWrap.replaceChildren(
      ...question.options.map((option) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "breed-option animate-pop";
        button.dataset.optionId = option.id;
        const label = document.createElement("span");
        label.textContent = option.label;
        button.append(label);
        button.addEventListener("click", () => this.answer(option.id, button));
        return button;
      }),
    );
  }

  async answer(optionId, button) {
    if (this.answering || this.locked || !this.question) return;
    this.answering = true;
    const buttons = [...this.el.optionsWrap.querySelectorAll("button")];
    buttons.forEach((b) => (b.disabled = true));
    const startedAt = performance.now();
    try {
      const result = await this.api.breedAnswer(this.sessionId, this.question.token, optionId);
      this.correct = result.breed_correct;
      this.el.progress.textContent = String(this.correct);
      if (result.correct) {
        button.classList.add("is-correct");
        button.insertAdjacentHTML("beforeend", CHECK);
        this.setFeedback(`¡Correcto! +${result.points_awarded}`, "text-correct", CHECK);
        this.onScore?.(result.total_score, result.points_awarded);
      } else {
        button.classList.add("is-incorrect");
        button.insertAdjacentHTML("beforeend", CROSS);
        const right = buttons.find((b) => b.textContent.trim() === result.correct_label);
        if (right) {
          right.classList.add("is-correct");
          right.insertAdjacentHTML("beforeend", CHECK);
        }
        this.setFeedback(`Era: ${result.correct_label}`, "text-incorrect", CROSS);
      }
      if (result.next_question) {
        // Precarga la siguiente foto mientras se muestra la retroalimentación.
        const img = new Image();
        img.src = result.next_question.image_url;
      }
      const wait = Math.max(0, FEEDBACK_MS - (performance.now() - startedAt));
      await new Promise((r) => setTimeout(r, wait));
      this.show(result.next_question);
    } catch (err) {
      if (err instanceof ApiError && (err.code === "breed_stage_closed" || err.code === "session_finished")) {
        this.lock();
      } else if (err instanceof ApiError && err.code === "already_answered") {
        // Recarga o doble envío: se pide la pregunta vigente al servidor.
        try {
          const data = await this.api.breedQuestion(this.sessionId);
          this.show(data.question);
        } catch (e) {
          this.onError?.(e);
        }
      } else {
        buttons.forEach((b) => (b.disabled = false));
        this.onError?.(err);
      }
    } finally {
      this.answering = false;
    }
  }

  setFeedback(text, colorClass, icon) {
    this.el.feedback.className = `flex min-h-[44px] items-center gap-3 text-2xl font-bold ${colorClass}`;
    this.el.feedback.innerHTML = icon;
    this.el.feedback.append(document.createTextNode(text));
  }

  lock() {
    this.locked = true;
    this.el.optionsWrap.querySelectorAll("button").forEach((b) => (b.disabled = true));
  }
}
