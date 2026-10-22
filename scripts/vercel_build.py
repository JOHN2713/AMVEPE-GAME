"""Build de Vercel (vercel.json → buildCommand).

1. Copia app/static a public/static para que el CDN de Vercel sirva CSS, JS, fuentes e imágenes.
   Flask sigue teniendo su copia en app/static para las imágenes del juego servidas por token.
2. Solo en producción (VERCEL_ENV=production): migraciones, carga de data/catalog.json y
   verificación de contenido (equivalente a `flask deploy`). Las previews no tocan la base de producción.
"""

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app" / "static"
DEST = ROOT / "public" / "static"


def copy_static() -> None:
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SRC, DEST, ignore=shutil.ignore_patterns("placeholders"))
    print(f"Estáticos copiados a {DEST.relative_to(ROOT)}")


def deploy_database() -> None:
    if os.environ.get("VERCEL_ENV") != "production":
        print(f"VERCEL_ENV={os.environ.get('VERCEL_ENV')!r}: se omiten migraciones (solo en producción).")
        return
    if not (os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")):
        sys.exit("ERROR: falta DATABASE_URL en las variables de entorno de producción.")
    sys.path.insert(0, str(ROOT))
    try:
        import flask_migrate  # noqa: F401
    except ImportError:
        # Por si el build corre antes de instalar las dependencias de la función.
        import subprocess

        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "-r", str(ROOT / "requirements.txt")], check=True)
    from flask_migrate import upgrade

    from app import create_app
    from app.services.catalog_service import content_report, load_catalog

    app = create_app()
    with app.app_context():
        upgrade(directory=str(ROOT / "migrations"))
        created, updated = load_catalog(ROOT / "data" / "catalog.json")
        print(f"Base de datos al día. Catálogo: {created} nuevas, {updated} actualizadas.")
        report = content_report()
        for line in report["warnings"] + report["problems"]:
            print(f"AVISO: {line}")
        if not report["ok"]:
            sys.exit("ERROR: no hay contenido aprobado suficiente para jugar.")


if __name__ == "__main__":
    copy_static()
    deploy_database()
