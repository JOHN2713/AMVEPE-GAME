"""Consulta del catálogo aprobado de imágenes y chequeo de suficiencia antes del evento."""

import json
from pathlib import Path

from flask import current_app
from sqlalchemy import select

from app.extensions import db
from app.models import AnimalAsset

# Distractores de respaldo, por especie, para cuando el catálogo aprobado tenga pocas razas distintas.
FALLBACK_BREEDS = {
    "dog": [
        "Labrador Retriever", "Golden Retriever", "Pastor Alemán", "Bulldog Francés", "Beagle", "Caniche (Poodle)",
        "Chihuahua", "Shih Tzu", "Husky Siberiano", "Dálmata", "Bóxer", "Schnauzer", "Pug", "Rottweiler",
        "Border Collie", "Yorkshire Terrier", "Cocker Spaniel", "Dóberman", "Pomerania", "Salchicha (Dachshund)",
    ],
    "cat": [
        "Persa", "Siamés", "Maine Coon", "Bengalí", "Ragdoll", "Esfinge (Sphynx)", "British Shorthair", "Azul Ruso",
        "Scottish Fold", "Angora Turco", "Siberiano", "Abisinio", "Bosque de Noruega", "Exótico de Pelo Corto",
    ],
}

CATALOG_FIELDS = ("species", "usage", "breed_external_id", "breed_name_es", "provider", "source_url", "local_path", "attribution")

MIN_MEMORY_ASSETS = 6
RECOMMENDED_BREED_QUESTIONS = 20


def playable_assets_query(include_placeholders: bool = True):
    query = select(AnimalAsset).where(AnimalAsset.active.is_(True), AnimalAsset.license_status == "approved")
    if not include_placeholders or not current_app.config["ALLOW_PLACEHOLDER_ASSETS"]:
        query = query.where(AnimalAsset.provider != "placeholder")
    return query


def playable_assets() -> list[AnimalAsset]:
    """Imágenes jugables. Las de prueba solo se usan mientras no haya fotos reales suficientes."""
    real = list(db.session.execute(playable_assets_query(include_placeholders=False)).scalars())
    if len([a for a in real if a.usable_for_memory]) >= MIN_MEMORY_ASSETS and any(a.usable_for_breed for a in real):
        return real
    return list(db.session.execute(playable_assets_query()).scalars())


def breed_names_by_species(assets: list[AnimalAsset]) -> dict[str, list[str]]:
    names: dict[str, set[str]] = {"dog": set(), "cat": set()}
    for asset in assets:
        if asset.usable_for_breed:
            names[asset.species].add(asset.breed_name_es.strip())
    return {species: sorted(values) for species, values in names.items()}


def content_report() -> dict:
    assets = playable_assets()
    memory = [a for a in assets if a.usable_for_memory]
    breed = [a for a in assets if a.usable_for_breed]
    breeds = breed_names_by_species(assets)
    # El tablero usa primero imágenes solo-memoria; las que falten se toman de las de raza y no se repiten en la etapa 2.
    memory_only = [a for a in memory if not a.usable_for_breed]
    estimated_questions = max(0, len(breed) - max(0, MIN_MEMORY_ASSETS - len(memory_only)))
    problems = []
    if len(memory) < MIN_MEMORY_ASSETS:
        problems.append(f"Se necesitan al menos {MIN_MEMORY_ASSETS} imágenes aprobadas para el tablero de memoria (hay {len(memory)}).")
    if estimated_questions < 1:
        problems.append("No hay imágenes aprobadas con raza verificada para la etapa 2.")
    warnings = []
    if 0 < estimated_questions < RECOMMENDED_BREED_QUESTIONS:
        warnings.append(f"Hay aprox. {estimated_questions} preguntas de raza; se recomiendan al menos {RECOMMENDED_BREED_QUESTIONS} para que no se agoten en 45 s.")
    if any(a.provider == "placeholder" for a in assets):
        warnings.append("Hay imágenes de prueba (placeholder) activas. No se usarán en producción.")
    return {
        "ok": not problems,
        "problems": problems,
        "warnings": warnings,
        "memory_assets": len(memory),
        "breed_assets": len(breed),
        "estimated_questions": estimated_questions,
        "dog_breeds": len(breeds["dog"]),
        "cat_breeds": len(breeds["cat"]),
    }


# --------------------------------------------------------------------------- exportar / cargar catálogo
# El disco de Railway es efímero: las imágenes aprobadas se versionan en Git junto con data/catalog.json
# y `flask deploy` las registra en PostgreSQL en cada despliegue.

def export_catalog(path: Path) -> int:
    assets = db.session.execute(
        select(AnimalAsset)
        .where(AnimalAsset.license_status == "approved", AnimalAsset.provider != "placeholder")
        .order_by(AnimalAsset.species, AnimalAsset.breed_name_es, AnimalAsset.source_url)
    ).scalars().all()
    items = [{**{f: getattr(a, f) for f in CATALOG_FIELDS}, "active": a.active, "metadata": a.metadata_json or {}} for a in assets]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "assets": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(items)


def load_catalog(path: Path) -> tuple[int, int]:
    static_dir = Path(current_app.static_folder)
    data = json.loads(path.read_text(encoding="utf-8"))
    created = updated = 0
    for item in data.get("assets", []):
        if not (static_dir / item["local_path"]).is_file():
            raise FileNotFoundError(f"Falta el archivo {item['local_path']} declarado en {path}")
        asset = db.session.execute(select(AnimalAsset).where(AnimalAsset.source_url == item["source_url"])).scalar_one_or_none()
        if asset is None:
            asset = AnimalAsset()
            db.session.add(asset)
            created += 1
        else:
            updated += 1
        for field in CATALOG_FIELDS:
            setattr(asset, field, item.get(field))
        asset.license_status = "approved"
        asset.active = bool(item.get("active", True))
        asset.metadata_json = item.get("metadata") or {}
    # Lo que ya no figura en el catálogo versionado deja de usarse en partidas.
    listed = {item["source_url"] for item in data.get("assets", [])}
    for asset in db.session.execute(select(AnimalAsset).where(AnimalAsset.active.is_(True))).scalars():
        if asset.source_url not in listed:
            asset.active = False
    db.session.commit()
    return created, updated
