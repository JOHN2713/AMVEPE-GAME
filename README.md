# Perseo Pets: Reto Animal — AMVEPE 2026

Juego de 90 segundos para el stand: registro, **memoria animal** (45 s) y **¿Qué raza es?** (45 s).
Flask + PostgreSQL (SQLite en local), Tailwind compilado y JavaScript sin frameworks.

## Puesta en marcha local (Windows)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
npm install
npm run build                      # copia Montserrat y compila app/static/css/styles.css
copy .env.example .env             # completa SECRET_KEY y ADMIN_PASSWORD_HASH
.venv\Scripts\flask db upgrade     # crea instance/dev.sqlite3
.venv\Scripts\flask seed-placeholders   # imágenes de prueba (solo desarrollo)
.venv\Scripts\flask run --debug
```

- Juego: http://127.0.0.1:5000 · Ranking público: `/ranking` · Administración: `/admin`
- Contraseña de admin: `flask hash-password` y pega el resultado en `ADMIN_PASSWORD_HASH` (entre comillas simples en `.env`).
- Pruebas: `.venv\Scripts\python -m pytest`
- Mientras editas plantillas/JS: `npm run watch:css`. **Versiona `app/static/css/styles.css` y `app/static/fonts/`**: el despliegue no ejecuta Node.

## Flujo de una partida

1. `POST /api/registrations` valida y normaliza (correo en minúsculas, celular en E.164). Un mismo correo en el evento reutiliza al participante y agrega una nueva evidencia de consentimiento.
2. `POST /api/game/sessions` prepara el tablero (12 cartas, 6 parejas) y la cola de preguntas. El navegador precarga todas las imágenes.
3. Tras la cuenta 3-2-1, `POST …/start` fija `started_at` en el servidor. El reloj del navegador se ancla al tiempo del servidor con `performance.now()`; recargar la página no reinicia los 90 s.
4. `…/memory-match`, `…/breed-question` y `…/breed-answer` validan etapa y tiempo en el servidor (tolerancia `ACTION_GRACE_SECONDS`).
5. `…/finish` es idempotente y calcula el total desde las acciones guardadas.

Las imágenes del juego se sirven por token opaco (`/game/img/c/<token>`, `/game/img/q/<token>`): ni la URL ni la respuesta JSON revelan parejas ni respuestas correctas.

## Preparar las imágenes (Pexels / Unsplash)

Todo lo importado entra como **pendiente** y no se usa hasta aprobarlo en `/admin/catalogo`, donde se confirma que la foto corresponde a la raza indicada.

```powershell
# Pexels (requiere PEXELS_API_KEY gratuita): lote de búsquedas sugeridas
.venv\Scripts\flask import-pexels --batch data/pexels_queries.csv
# o una búsqueda puntual
.venv\Scripts\flask import-pexels --query "beagle dog" --species dog --usage both --breed "Beagle" --limit 5

# Magnific (antes Freepik; requiere MAGNIFIC_API_KEY en .env). Solo fotos reales, sin IA; cada descarga consume créditos
.venv\Scripts\flask import-magnific --query "beagle dog" --species dog --breed "Beagle" --limit 1
.venv\Scripts\flask import-magnific --batch data/pexels_queries.csv

# Fotos elegidas a mano (p. ej. descargadas de unsplash.com): ver data/manifest.example.csv
.venv\Scripts\flask import-manifest ruta\manifest.csv

.venv\Scripts\flask content-check       # falla si no alcanza el contenido
.venv\Scripts\flask export-catalog      # guarda las aprobadas en data/catalog.json
```

Las fotos se guardan completas (sin recortar al animal) en un cuadrado de 1000 px WebP con nombre por hash, en `app/static/img/animals/`. **Versiona en Git esa carpeta y `data/catalog.json`**: el disco del servidor no es persistente y el despliegue vuelve a registrar el catálogo en PostgreSQL.

Recomendado: al menos 6 imágenes de "otros animales" para memoria y 25 o más fotos de razas (perros y gatos) para que las preguntas no se agoten en 45 s.

## Despliegue en Vercel

1. En Vercel: **Add New → Project** e importa el repositorio de GitHub. Vercel detecta Flask (`wsgi.py`) y Python 3.12 (`.python-version`).
2. En el proyecto, **Storage → Create Database → Neon (Postgres)** y conéctala al proyecto: crea `DATABASE_URL` automáticamente.
3. **Settings → Environment Variables** (entorno Production): `APP_ENV=production`, `SECRET_KEY`, `EVENT_CODE`, `TERMS_VERSION`, `PRIVACY_VERSION`, `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`, `PUBLIC_DEMO_URL`. La clave de Magnific no hace falta.
4. Despliega. El build (`scripts/vercel_build.py`) copia `app/static` a `public/static` para el CDN y, **solo en producción**, aplica migraciones, carga `data/catalog.json` y falla si no hay contenido suficiente. Los despliegues de preview no tocan la base de producción.
5. Abre la URL `*.vercel.app` (o conecta tu dominio) y prueba `/health`, una partida completa, el ranking y la exportación CSV.

Alternativa manual (por ejemplo, si el build no pudo migrar): desde tu equipo, con la URL de Neon,
`$env:DATABASE_URL="postgresql://..."; .venv\Scripts\flask deploy`.

Notas: el disco de Vercel es de solo lectura (las importaciones de fotos se hacen siempre en local) y cada despliegue de `main` publica producción. Elige para Neon una región cercana (p. ej. `us-east`) y revisa sus backups antes del evento. `Dockerfile` y `railway.json` quedan como alternativa para Railway.

## Operación en la feria

- Abre el juego en pantalla completa (F11, o Edge/Chrome con `--kiosk`). Todo se maneja con el mouse.
- La pantalla de resultados vuelve sola al registro tras 90 s sin actividad. También puedes usar "Nuevo jugador".
- En `/admin` puedes anular una partida (deja de contar para el ranking) y exportar los CSV.
- `flask expire-sessions` cierra partidas abandonadas; el ranking y el panel también lo hacen solos.
- Tras el plazo de conservación: `flask anonymize-event --yes` (irreversible).

## Pendiente antes de publicar

- [ ] Completar los campos `[entre corchetes]` de `app/templates/partials/terms_content.html` y `privacy_content.html`, y obtener la revisión legal (LOPDP Ecuador).
- [ ] Definir `PUBLIC_DEMO_URL` (QR de la pantalla final).
- [ ] Definir si hay premio (cláusula 5) y la política de partidas por persona (`MAX_SESSIONS_PER_PARTICIPANT`).
- [ ] Importar, revisar y aprobar las fotos reales; ejecutar `flask export-catalog`.
