"""Atajo para preparar el catálogo sin recordar los comandos de Flask.

Uso (con el entorno virtual activo):
    python scripts/import_animal_content.py placeholders
    python scripts/import_animal_content.py pexels data/pexels_queries.csv
    python scripts/import_animal_content.py magnific data/pexels_queries.csv
    python scripts/import_animal_content.py manifest ruta/al/manifest.csv
    python scripts/import_animal_content.py check
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from app.services import animal_api_service as content  # noqa: E402
from app.services.catalog_service import content_report  # noqa: E402


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    command, *rest = argv
    app = create_app()
    with app.app_context():
        if command == "placeholders":
            content.seed_placeholders()
        elif command in content.IMPORTERS:
            print(f"{content.import_batch(Path(rest[0] if rest else 'data/pexels_queries.csv'), command)} imágenes pendientes de revisión.")
        elif command == "manifest":
            print(f"{content.import_manifest(Path(rest[0]))} imágenes pendientes de revisión.")
        elif command == "check":
            report = content_report()
            for line in report["problems"] + report["warnings"]:
                print(line)
            print("OK" if report["ok"] else "FALTA CONTENIDO")
            return 0 if report["ok"] else 1
        else:
            print(__doc__)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
