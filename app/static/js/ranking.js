import { api } from "./api.js";

const REFRESH_MS = 15000;
const body = document.getElementById("ranking-body");

function cell(text, className = "") {
  const td = document.createElement("td");
  td.className = `px-6 py-4 ${className}`;
  td.textContent = text;
  return td;
}

async function refresh() {
  try {
    const { ranking } = await api.ranking(10);
    if (!ranking.length) {
      const tr = document.createElement("tr");
      tr.append(cell("¡Aún no hay partidas! Sé el primero en jugar.", "py-10 text-center text-muted"));
      tr.firstChild.colSpan = 5;
      body.replaceChildren(tr);
      return;
    }
    body.replaceChildren(
      ...ranking.map((row) => {
        const tr = document.createElement("tr");
        if (row.position <= 3) tr.className = "bg-primary-soft";
        tr.append(
          cell(String(row.position), "font-extrabold"),
          cell(row.player, "font-semibold"),
          cell(String(row.pairs_found), "text-right tabular-nums"),
          cell(String(row.breed_correct), "text-right tabular-nums"),
          cell(String(row.total_score), "text-right text-3xl font-extrabold text-primary tabular-nums"),
        );
        return tr;
      }),
    );
  } catch {
    /* se reintenta en el siguiente ciclo */
  }
}

refresh();
setInterval(refresh, REFRESH_MS);
