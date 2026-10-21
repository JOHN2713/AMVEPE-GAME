// Reloj de la partida anclado al tiempo transcurrido que informa el servidor.
// Usa performance.now() (monótono): cambiar la hora del equipo o de pestaña no lo altera.

export class GameClock {
  constructor({ stageSeconds, totalSeconds }) {
    this.stageMs = stageSeconds * 1000;
    this.totalMs = totalSeconds * 1000;
    // Fin de la etapa 1: 45 s, o antes si se completó el tablero (lo informa el servidor).
    this.memoryEndMs = this.stageMs;
    this.anchor = null;
  }

  setMemoryEnd(ms) {
    if (typeof ms === "number") this.memoryEndMs = Math.min(this.stageMs, ms);
  }

  /** elapsedMs: tiempo transcurrido según el servidor; rttMs: ida y vuelta de la petición. */
  sync(elapsedMs, rttMs = 0) {
    this.anchor = performance.now() - elapsedMs - rttMs / 2;
  }

  get elapsedMs() {
    if (this.anchor === null) return 0;
    return Math.max(0, performance.now() - this.anchor);
  }

  get remainingMs() {
    return Math.max(0, this.totalMs - this.elapsedMs);
  }

  get stage() {
    const e = this.elapsedMs;
    if (e < this.memoryEndMs) return "memory";
    if (e < this.totalMs) return "breed";
    return "finished";
  }

  /** Fracción [0..1] consumida de cada etapa, para las barras de progreso. */
  stageProgress() {
    const e = this.elapsedMs;
    const breedMs = this.totalMs - this.memoryEndMs;
    const memory = e >= this.memoryEndMs ? 1 : e / this.stageMs;
    return [Math.min(1, memory), Math.min(1, Math.max(0, e - this.memoryEndMs) / breedMs)];
  }
}

export function formatTime(ms) {
  const total = Math.ceil(ms / 1000);
  const m = Math.floor(total / 60);
  const s = String(total % 60).padStart(2, "0");
  return `${m}:${s}`;
}
