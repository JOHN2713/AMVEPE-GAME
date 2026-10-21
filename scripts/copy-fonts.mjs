// Copia Montserrat desde @fontsource a app/static/fonts para no depender de Google Fonts en la feria.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "node_modules", "@fontsource", "montserrat", "files");
const dest = join(root, "app", "static", "fonts");
mkdirSync(dest, { recursive: true });

// El subconjunto latin cubre español (á, é, í, ó, ú, ñ, ü, ¿, ¡).
for (const weight of [400, 500, 600, 700, 800]) {
  const file = `montserrat-latin-${weight}-normal.woff2`;
  copyFileSync(join(src, file), join(dest, file));
}
console.log("Fuentes Montserrat copiadas a app/static/fonts");
