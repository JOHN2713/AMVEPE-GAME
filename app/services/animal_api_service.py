"""Preparación del catálogo de imágenes. Solo se usa desde comandos de administración, nunca durante una partida.

Fuentes:
- Pexels API (licencia Pexels: uso comercial gratuito, sin atribución obligatoria pero recomendada).
- Magnific API (antes Freepik): fotos de stock según la licencia del plan; se excluyen imágenes generadas por IA.
- Manifiesto CSV con fotos elegidas a mano (p. ej. descargadas desde unsplash.com con su licencia).

Todo lo importado queda en license_status='pending' y active=False hasta que alguien revise en /admin
que la foto corresponde a la raza indicada.
"""

import csv
import hashlib
import io
import re
import unicodedata
from pathlib import Path

import requests
from flask import current_app
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from sqlalchemy import select

from app.extensions import db
from app.models import AnimalAsset
from app.models.animal_asset import SPECIES, USAGES

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
IMAGE_SIZE = 1000
MAX_TRIM = 0.12
HTTP_TIMEOUT = 20
# Marca en metadata de las imágenes procesadas con la foto completa (sin recorte).
PROCESSING_VERSION = "contain-v2"


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "img"


def optimize_image(raw: bytes) -> bytes:
    """Cuadrado de 1000 px en WebP con la foto COMPLETA (sin recortar al animal).

    La foto se encaja entera y el espacio sobrante se rellena con una versión desenfocada
    de la misma imagen: tamaño consistente para cartas y preguntas sin cortar cabezas ni patas.
    """
    size = (IMAGE_SIZE, IMAGE_SIZE)
    with Image.open(io.BytesIO(raw)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        # Recorte leve y centrado del lado largo (máx. 12 %): agranda al animal sin cortarlo.
        long_side, short_side = max(img.size), min(img.size)
        target = max(short_side, int(long_side * (1 - MAX_TRIM)))
        if target < long_side:
            if img.width > img.height:
                left = (img.width - target) // 2
                img = img.crop((left, 0, left + target, img.height))
            else:
                top = (img.height - target) // 2
                img = img.crop((0, top, img.width, top + target))
        studio_color = _plain_border_color(img)
        if studio_color:
            # Foto de estudio (fondo liso): se extiende el mismo color en lugar de desenfocar.
            background = Image.new("RGB", size, studio_color)
        else:
            background = ImageOps.fit(img, size, method=Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(36))
            background = ImageEnhance.Brightness(background).enhance(0.92)
        foreground = ImageOps.contain(img, size, method=Image.Resampling.LANCZOS)
        background.paste(foreground, ((size[0] - foreground.width) // 2, (size[1] - foreground.height) // 2))
        out = io.BytesIO()
        background.save(out, "WEBP", quality=82, method=6)
        return out.getvalue()


def _plain_border_color(img: Image.Image) -> tuple[int, int, int] | None:
    """Color del borde si es claro y uniforme (fondo de estudio); None en fotos con escenario."""
    small = img.resize((64, 64))
    pixels = [small.getpixel((x, y)) for x in range(64) for y in (0, 1, 62, 63)]
    pixels += [small.getpixel((x, y)) for y in range(64) for x in (0, 1, 62, 63)]
    mean = tuple(sum(p[i] for p in pixels) // len(pixels) for i in range(3))
    spread = max(max(abs(p[i] - mean[i]) for i in range(3)) for p in pixels)
    if min(mean) >= 200 and spread <= 40:
        return mean
    return None


def _store_file(raw: bytes) -> str:
    animals_dir: Path = current_app.config["ANIMALS_DIR"]
    animals_dir.mkdir(parents=True, exist_ok=True)
    optimized = optimize_image(raw)
    # Nombre basado en hash: no revela la raza en la URL del archivo.
    digest = hashlib.sha256(optimized).hexdigest()[:20]
    filename = f"{digest}.webp"
    (animals_dir / filename).write_bytes(optimized)
    # Original sin procesar (fuera de Git) para poder reajustar el encuadre sin volver a descargar.
    originals = Path(current_app.instance_path) / "originals"
    originals.mkdir(parents=True, exist_ok=True)
    (originals / f"{digest}.orig").write_bytes(raw)
    return f"img/animals/{filename}"


def _exists(source_url: str) -> bool:
    return db.session.execute(select(AnimalAsset.id).where(AnimalAsset.source_url == source_url)).first() is not None


def import_from_pexels(query: str, species: str, usage: str, breed_name_es: str | None, limit: int = 5, log=print) -> int:
    api_key = current_app.config["PEXELS_API_KEY"]
    if not api_key:
        raise RuntimeError("Configura PEXELS_API_KEY en el entorno para importar desde Pexels.")
    _check_species_usage(species, usage)
    response = requests.get(
        PEXELS_SEARCH_URL,
        headers={"Authorization": api_key},
        params={"query": query, "per_page": min(limit * 2, 40), "orientation": "square"},
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    created = 0
    for photo in response.json().get("photos", []):
        if created >= limit:
            break
        source_url = photo["url"]
        if _exists(source_url):
            continue
        image = requests.get(photo["src"]["large2x"], timeout=HTTP_TIMEOUT)
        image.raise_for_status()
        local_path = _store_file(image.content)
        db.session.add(
            AnimalAsset(
                species=species,
                usage=usage,
                breed_external_id=slugify(breed_name_es) if breed_name_es else None,
                breed_name_es=breed_name_es,
                provider="pexels",
                source_url=source_url,
                local_path=local_path,
                license_status="pending",
                attribution=f"Foto de {photo.get('photographer', 'autor desconocido')} en Pexels",
                active=False,
                metadata_json={
                    "pexels_id": photo.get("id"),
                    "photographer_url": photo.get("photographer_url"),
                    "alt": photo.get("alt"),
                    "query": query,
                    "license": "Pexels License https://www.pexels.com/license/",
                },
            )
        )
        db.session.commit()
        created += 1
        log(f"  + {breed_name_es or query}: {source_url}")
    return created


def import_from_magnific(query: str, species: str, usage: str, breed_name_es: str | None, limit: int = 5, log=print) -> int:
    """Busca fotos reales (sin IA) en Magnific y descarga las primeras `limit` que no estén ya en el catálogo.

    Cada descarga consume la cuota/créditos del plan de Magnific.
    """
    cfg = current_app.config
    api_key = cfg["MAGNIFIC_API_KEY"]
    if not api_key:
        raise RuntimeError("Configura MAGNIFIC_API_KEY en el archivo .env para importar desde Magnific.")
    _check_species_usage(species, usage)
    base = cfg["MAGNIFIC_API_BASE"].rstrip("/")
    headers = {"x-magnific-api-key": api_key, "Accept-Language": "en-US"}
    response = requests.get(
        f"{base}/v1/resources",
        headers=headers,
        params={
            "term": query,
            "limit": min(limit * 3, 50),
            "order": "relevance",
            "filters[content_type][photo]": 1,
            # Las fotos generadas por IA no garantizan rasgos reales de la raza.
            "filters[ai-generated][excluded]": 1,
        },
        timeout=HTTP_TIMEOUT,
    )
    _raise_for_magnific(response)
    created = 0
    for item in response.json().get("data", []):
        if created >= limit:
            break
        source_url = item.get("url") or f"magnific://{item.get('id')}"
        if _exists(source_url):
            continue
        local_path = _download_magnific(base, headers, item["id"], source_url, log)
        if local_path is None:
            continue
        author = (item.get("author") or {}).get("name") or "autor desconocido"
        licenses = item.get("licenses") or []
        license_type = licenses[0].get("type") if licenses else None
        db.session.add(
            AnimalAsset(
                species=species,
                usage=usage,
                breed_external_id=slugify(breed_name_es) if breed_name_es else None,
                breed_name_es=breed_name_es,
                provider="magnific",
                source_url=source_url,
                local_path=local_path,
                license_status="pending",
                attribution=f"Imagen de {author} en Magnific (Freepik)",
                active=False,
                metadata_json={
                    "magnific_id": item.get("id"),
                    "title": item.get("title"),
                    "author": item.get("author"),
                    "license_type": license_type,
                    "licenses": licenses,
                    "query": query,
                    "processing": PROCESSING_VERSION,
                },
            )
        )
        db.session.commit()
        created += 1
        log(f"  + {breed_name_es or query} [{license_type or 'licencia ?'}]: {source_url}")
    return created


def _download_magnific(base: str, headers: dict, resource_id, source_url: str, log) -> str | None:
    """Descarga el archivo original de un recurso (consume cuota del plan) y lo guarda procesado."""
    download = requests.get(f"{base}/v1/resources/{resource_id}/download", headers=headers, timeout=HTTP_TIMEOUT)
    if download.status_code == 402:
        raise RuntimeError("Magnific: créditos insuficientes (402). Recarga créditos y vuelve a ejecutar el comando; continúa donde quedó.")
    if download.status_code == 403:
        log(f"  - sin permiso para descargar {source_url} (licencia del plan); se omite")
        return None
    _raise_for_magnific(download)
    data = download.json().get("data") or {}
    if isinstance(data, list):
        data = data[0] if data else {}
    file_url = data.get("url")
    if not file_url:
        log(f"  - la descarga de {source_url} no devolvió URL; se omite")
        return None
    image = requests.get(file_url, timeout=HTTP_TIMEOUT)
    image.raise_for_status()
    try:
        return _store_file(image.content)
    except OSError:
        log(f"  - el archivo de {source_url} no es una imagen válida (¿ZIP?); se omite")
        return None


def refresh_magnific_images(limit: int | None = None, log=print) -> int:
    """Vuelve a descargar las fotos de Magnific ya catalogadas y las reprocesa sin recorte.

    Conserva raza, uso y aprobación de cada registro; solo cambia el archivo.
    """
    cfg = current_app.config
    if not cfg["MAGNIFIC_API_KEY"]:
        raise RuntimeError("Configura MAGNIFIC_API_KEY en el archivo .env para descargar desde Magnific.")
    base = cfg["MAGNIFIC_API_BASE"].rstrip("/")
    headers = {"x-magnific-api-key": cfg["MAGNIFIC_API_KEY"], "Accept-Language": "en-US"}
    assets = db.session.execute(
        select(AnimalAsset).where(AnimalAsset.provider == "magnific").order_by(AnimalAsset.created_at)
    ).scalars().all()
    static_dir = Path(current_app.static_folder)
    done = 0
    for asset in assets:
        if limit is not None and done >= limit:
            break
        meta = asset.metadata_json or {}
        if not meta.get("magnific_id") or meta.get("processing") == PROCESSING_VERSION:
            continue
        new_path = _download_magnific(base, headers, meta["magnific_id"], asset.source_url, log)
        if new_path is None:
            continue
        old_path = asset.local_path
        asset.local_path = new_path
        asset.metadata_json = {**meta, "processing": PROCESSING_VERSION}
        db.session.commit()
        if old_path != new_path:
            (static_dir / old_path).unlink(missing_ok=True)
        done += 1
        log(f"  ~ {asset.breed_name_es or meta.get('query')}: {new_path}")
    return done


def _raise_for_magnific(response) -> None:
    if response.status_code == 401:
        raise RuntimeError("Magnific rechazó la clave (401). Revisa MAGNIFIC_API_KEY y que el plan permita uso por API.")
    if response.status_code == 429:
        raise RuntimeError("Magnific: límite de peticiones alcanzado (429). Espera un momento y vuelve a intentar.")
    response.raise_for_status()


IMPORTERS = {"pexels": import_from_pexels, "magnific": import_from_magnific}


def import_batch(csv_path: Path, provider: str = "pexels", log=print) -> int:
    """CSV con columnas: species,usage,breed_name_es,query,count"""
    importer = IMPORTERS[provider]
    total = 0
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            breed = (row.get("breed_name_es") or "").strip() or None
            log(f"Buscando '{row['query']}' en {provider}...")
            total += importer(row["query"], row["species"].strip(), row["usage"].strip(), breed, int(row.get("count") or 3), log=log)
    return total


def import_manifest(csv_path: Path, log=print) -> int:
    """Fotos elegidas a mano. CSV: species,usage,breed_name_es,provider,source_url,image,attribution

    image puede ser una ruta local (relativa al CSV) o una URL de descarga directa.
    """
    created = 0
    base = csv_path.parent
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            species, usage = row["species"].strip(), row["usage"].strip()
            _check_species_usage(species, usage)
            source_url = row["source_url"].strip()
            if _exists(source_url):
                log(f"  = ya existe: {source_url}")
                continue
            image_ref = row["image"].strip()
            if image_ref.startswith(("http://", "https://")):
                resp = requests.get(image_ref, timeout=HTTP_TIMEOUT)
                resp.raise_for_status()
                raw = resp.content
            else:
                raw = (base / image_ref).read_bytes()
            breed = (row.get("breed_name_es") or "").strip() or None
            db.session.add(
                AnimalAsset(
                    species=species,
                    usage=usage,
                    breed_external_id=slugify(breed) if breed else None,
                    breed_name_es=breed,
                    provider=row.get("provider", "manual").strip() or "manual",
                    source_url=source_url,
                    local_path=_store_file(raw),
                    license_status="pending",
                    attribution=(row.get("attribution") or "").strip() or None,
                    active=False,
                    metadata_json={"manifest": csv_path.name},
                )
            )
            db.session.commit()
            created += 1
            log(f"  + {breed or species}: {source_url}")
    return created


def _check_species_usage(species: str, usage: str) -> None:
    if species not in SPECIES:
        raise ValueError(f"Especie inválida: {species}. Usa una de {SPECIES}")
    if usage not in USAGES:
        raise ValueError(f"Uso inválido: {usage}. Usa uno de {USAGES}")
    if usage in ("breed", "both") and species == "other":
        raise ValueError("Las preguntas de raza solo admiten perros (dog) o gatos (cat).")


# --------------------------------------------------------------------------- imágenes de prueba

PLACEHOLDERS = [
    # (especie, uso, raza, emoji, color)
    ("other", "memory", None, "🐰", "#FDE68A"),
    ("other", "memory", None, "🦜", "#BBF7D0"),
    ("other", "memory", None, "🐹", "#FECACA"),
    ("other", "memory", None, "🐢", "#BFDBFE"),
    ("other", "memory", None, "🐴", "#DDD6FE"),
    ("other", "memory", None, "🐠", "#A5F3FC"),
    ("dog", "breed", "Labrador Retriever", "🐕", "#E7E5E4"),
    ("dog", "breed", "Golden Retriever", "🐕", "#FEF3C7"),
    ("dog", "breed", "Pastor Alemán", "🐕‍🦺", "#E5E7EB"),
    ("dog", "breed", "Bulldog Francés", "🐶", "#FCE7F3"),
    ("dog", "breed", "Beagle", "🐶", "#DCFCE7"),
    ("dog", "breed", "Caniche (Poodle)", "🐩", "#EDE9FE"),
    ("dog", "breed", "Chihuahua", "🐶", "#FFEDD5"),
    ("dog", "breed", "Husky Siberiano", "🐺", "#E0F2FE"),
    ("dog", "breed", "Dálmata", "🐕", "#F5F5F4"),
    ("dog", "breed", "Schnauzer", "🐶", "#ECFCCB"),
    ("dog", "breed", "Shih Tzu", "🐶", "#FAE8FF"),
    ("dog", "breed", "Border Collie", "🐕", "#CCFBF1"),
    ("cat", "breed", "Persa", "🐈", "#FEE2E2"),
    ("cat", "breed", "Siamés", "🐈", "#FEF9C3"),
    ("cat", "breed", "Maine Coon", "🐈", "#E0E7FF"),
    ("cat", "breed", "Bengalí", "🐆", "#FFEDD5"),
    ("cat", "breed", "Ragdoll", "🐱", "#F3E8FF"),
    ("cat", "breed", "Esfinge (Sphynx)", "🐱", "#FCE7F3"),
    ("cat", "breed", "Azul Ruso", "🐈‍⬛", "#DBEAFE"),
    ("cat", "breed", "British Shorthair", "🐱", "#F1F5F9"),
]


def _placeholder_svg(emoji: str, color: str, index: int) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 800" width="800" height="800">'
        f'<rect width="800" height="800" fill="{color}"/>'
        f'<circle cx="400" cy="380" r="250" fill="#ffffff" opacity="0.55"/>'
        f'<text x="400" y="470" font-size="300" text-anchor="middle">{emoji}</text>'
        f'<text x="400" y="740" font-size="44" font-family="Arial" text-anchor="middle" fill="#030712" opacity="0.5">IMAGEN DE PRUEBA {index:02d}</text>'
        f"</svg>"
    )


def seed_placeholders(log=print) -> int:
    """Catálogo de prueba para desarrollo local. El juego los ignora si ALLOW_PLACEHOLDER_ASSETS es falso."""
    animals_dir: Path = current_app.config["ANIMALS_DIR"] / "placeholders"
    animals_dir.mkdir(parents=True, exist_ok=True)
    created = 0
    for index, (species, usage, breed, emoji, color) in enumerate(PLACEHOLDERS, start=1):
        source_url = f"placeholder://{index}"
        if _exists(source_url):
            continue
        filename = f"ph-{hashlib.sha256(source_url.encode()).hexdigest()[:12]}.svg"
        (animals_dir / filename).write_text(_placeholder_svg(emoji, color, index), encoding="utf-8")
        db.session.add(
            AnimalAsset(
                species=species, usage=usage, breed_external_id=slugify(breed) if breed else None, breed_name_es=breed,
                provider="placeholder", source_url=source_url, local_path=f"img/animals/placeholders/{filename}",
                license_status="approved", attribution="Imagen de prueba generada", active=True, metadata_json={"placeholder": True},
            )
        )
        created += 1
    db.session.commit()
    log(f"{created} imágenes de prueba creadas.")
    return created


def reprocess_from_originals(log=print) -> int:
    """Rehace los WebP con el procesamiento actual usando los originales de instance/originals (sin descargas)."""
    originals = Path(current_app.instance_path) / "originals"
    static_dir = Path(current_app.static_folder)
    done = 0
    for asset in db.session.execute(select(AnimalAsset).where(AnimalAsset.provider != "placeholder")).scalars().all():
        original = originals / f"{Path(asset.local_path).stem}.orig"
        if not original.is_file():
            continue
        raw = original.read_bytes()
        old_path = asset.local_path
        new_path = _store_file(raw)
        if new_path == old_path:
            continue
        asset.local_path = new_path
        db.session.commit()
        (static_dir / old_path).unlink(missing_ok=True)
        original.unlink(missing_ok=True)
        done += 1
        log(f"  ~ {asset.breed_name_es or (asset.metadata_json or {}).get('query')}: {new_path}")
    return done
