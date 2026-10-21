"""Comandos de operación: `flask <comando>`. Ver README para el flujo de preparación del contenido."""

import hashlib
import sys
from pathlib import Path

import click
from flask import Flask, current_app
from sqlalchemy import select
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import Participant
from app.models.base import utcnow

DEFAULT_CATALOG = Path("data/catalog.json")


def register_cli(app: Flask) -> None:
    @app.cli.command("seed-placeholders")
    def seed_placeholders_cmd():
        """Crea imágenes de prueba para desarrollo local (no se usan en producción)."""
        from app.services.animal_api_service import seed_placeholders

        seed_placeholders(log=click.echo)

    def _stock_import_options(fn):
        fn = click.option("--batch", "batch_file", type=click.Path(exists=True, path_type=Path), help="CSV con búsquedas (data/pexels_queries.csv)")(fn)
        fn = click.option("--query", help="Búsqueda en inglés, p. ej. 'beagle dog'")(fn)
        fn = click.option("--species", type=click.Choice(["dog", "cat", "other"]))(fn)
        fn = click.option("--usage", type=click.Choice(["memory", "breed", "both"]), default="both")(fn)
        fn = click.option("--breed", "breed_name_es", help="Nombre de la raza en español")(fn)
        fn = click.option("--limit", default=3, show_default=True)(fn)
        return fn

    def _run_stock_import(provider, batch_file, query, species, usage, breed_name_es, limit):
        from app.services.animal_api_service import IMPORTERS, import_batch

        try:
            if batch_file:
                total = import_batch(batch_file, provider, log=click.echo)
            else:
                if not query or not species:
                    raise click.UsageError("Indica --batch o bien --query y --species.")
                total = IMPORTERS[provider](query, species, usage, breed_name_es, limit, log=click.echo)
        except RuntimeError as err:
            raise click.ClickException(str(err))
        click.echo(f"{total} imágenes importadas como 'pending'. Revísalas en /admin/catalogo.")

    @app.cli.command("import-pexels")
    @_stock_import_options
    def import_pexels_cmd(**kwargs):
        """Descarga candidatas desde Pexels. Quedan pendientes de revisión en /admin/catalogo."""
        _run_stock_import("pexels", **kwargs)

    @app.cli.command("import-magnific")
    @_stock_import_options
    def import_magnific_cmd(**kwargs):
        """Descarga fotos (sin IA) desde Magnific/Freepik. Consume créditos del plan. Quedan pendientes en /admin/catalogo."""
        _run_stock_import("magnific", **kwargs)

    @app.cli.command("refresh-magnific")
    @click.option("--limit", type=int, default=None, help="Máximo de fotos a reprocesar (para probar)")
    def refresh_magnific_cmd(limit):
        """Vuelve a descargar las fotos de Magnific y las guarda completas, sin recorte (consume cuota)."""
        from app.services.animal_api_service import refresh_magnific_images

        try:
            total = refresh_magnific_images(limit, log=click.echo)
        except RuntimeError as err:
            raise click.ClickException(str(err))
        click.echo(f"{total} fotos reprocesadas. Ejecuta `flask export-catalog` para actualizar data/catalog.json.")

    @app.cli.command("reprocess-images")
    def reprocess_images_cmd():
        """Rehace las imágenes desde los originales guardados en instance/originals (no consume cuota)."""
        from app.services.animal_api_service import reprocess_from_originals

        click.echo(f"{reprocess_from_originals(log=click.echo)} imágenes reprocesadas. Ejecuta `flask export-catalog`.")

    @app.cli.command("import-manifest")
    @click.argument("csv_file", type=click.Path(exists=True, path_type=Path))
    def import_manifest_cmd(csv_file):
        """Importa fotos elegidas a mano (p. ej. Unsplash) desde un CSV. Ver data/manifest.example.csv."""
        from app.services.animal_api_service import import_manifest

        total = import_manifest(csv_file, log=click.echo)
        click.echo(f"{total} imágenes importadas como 'pending'. Revísalas en /admin/catalogo.")

    @app.cli.command("content-check")
    def content_check_cmd():
        """Falla (código 1) si no hay suficiente contenido aprobado para jugar."""
        from app.services.catalog_service import content_report

        report = content_report()
        click.echo(
            f"Memoria: {report['memory_assets']} · Raza: {report['breed_assets']} "
            f"(perros {report['dog_breeds']} razas, gatos {report['cat_breeds']} razas) · Preguntas estimadas: {report['estimated_questions']}"
        )
        for warning in report["warnings"]:
            click.echo(f"AVISO: {warning}")
        for problem in report["problems"]:
            click.echo(f"ERROR: {problem}", err=True)
        if not report["ok"]:
            sys.exit(1)
        click.echo("Contenido listo para jugar.")

    @app.cli.command("export-catalog")
    @click.argument("json_file", type=click.Path(path_type=Path), default=DEFAULT_CATALOG)
    def export_catalog_cmd(json_file):
        """Guarda las imágenes aprobadas (curadas en local) para versionarlas y cargarlas en producción."""
        from app.services.catalog_service import export_catalog

        click.echo(f"{export_catalog(json_file)} imágenes aprobadas exportadas a {json_file}.")

    @app.cli.command("load-catalog")
    @click.argument("json_file", type=click.Path(path_type=Path), default=DEFAULT_CATALOG)
    def load_catalog_cmd(json_file):
        """Carga/actualiza el catálogo aprobado en la base de datos (idempotente)."""
        from app.services.catalog_service import load_catalog

        if not json_file.exists():
            click.echo(f"No existe {json_file}; se omite la carga del catálogo.")
            return
        created, updated = load_catalog(json_file)
        click.echo(f"Catálogo cargado: {created} nuevas, {updated} actualizadas.")

    @app.cli.command("deploy")
    @click.pass_context
    def deploy_cmd(ctx):
        """Paso previo al despliegue en Railway: migraciones + catálogo + verificación de contenido."""
        from flask_migrate import upgrade

        from app.services.catalog_service import content_report

        upgrade()
        ctx.invoke(load_catalog_cmd, json_file=DEFAULT_CATALOG)
        report = content_report()
        for line in report["warnings"] + report["problems"]:
            click.echo(f"AVISO: {line}")

    @app.cli.command("hash-password")
    @click.password_option()
    def hash_password_cmd(password):
        """Genera el valor para ADMIN_PASSWORD_HASH."""
        if len(password) < 12:
            raise click.BadParameter("Usa al menos 12 caracteres.")
        click.echo(generate_password_hash(password, method="scrypt"))

    @app.cli.command("expire-sessions")
    def expire_sessions_cmd():
        """Cierra partidas abandonadas sin finalizar."""
        from app.services.game_service import expire_stale_sessions

        click.echo(f"{expire_stale_sessions()} partidas marcadas como expiradas.")

    @app.cli.command("anonymize-event")
    @click.option("--yes", is_flag=True, help="Confirma la operación irreversible.")
    def anonymize_event_cmd(yes):
        """Anonimiza nombre, correo y celular de todos los participantes del evento (tras el plazo de conservación)."""
        event_code = current_app.config["EVENT_CODE"]
        if not yes:
            raise click.UsageError(f"Operación irreversible sobre {event_code}. Repite con --yes para confirmar.")
        participants = db.session.execute(
            select(Participant).where(Participant.event_code == event_code, Participant.anonymized_at.is_(None))
        ).scalars().all()
        now = utcnow()
        for p in participants:
            token = hashlib.sha256(f"{p.id}".encode()).hexdigest()[:16]
            p.full_name = "Anonimizado"
            p.email = f"anon-{token}@invalid"
            p.email_normalized = f"anon-{token}@invalid"
            p.phone_e164 = "+000000000000"
            p.anonymized_at = now
        db.session.commit()
        click.echo(f"{len(participants)} participantes anonimizados. Los puntajes se conservan para estadísticas.")
