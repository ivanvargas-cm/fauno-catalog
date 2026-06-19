#!/usr/bin/env python3
"""
main.py — Orquestador del sistema Fauno Meta Catalog Overlay

Uso básico:
  python main.py --csv productos.csv

Uso con Google Sheets:
  python main.py --sheet-id 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms

Uso en GitHub Actions (automático):
  python main.py --sheet-id $SHEET_ID --github-push

Opciones:
  --csv PATH            CSV con productos (exportado de Dataslayer/Sheets)
  --sheet-id ID         ID del Google Sheet de Dataslayer
  --worksheet NAME      Nombre del worksheet (default: primera hoja)
  --only-sale           Solo procesar productos con oferta activa
  --product-ids IDs     Solo estos IDs (separados por coma)
  --dry-run             Parsea datos sin generar imágenes
  --github-push         Commit y push de imágenes al repo para GitHub Pages
  --github-repo REPO    Repo GitHub (ej: miusuario/fauno-catalog-images)
  --base-url URL        URL base de las imágenes publicadas
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Ajustar sys.path para importar desde src/
sys.path.insert(0, str(Path(__file__).parent / "src"))

from image_generator import ImageGenerator
from sheets_feed import (
    read_products_from_csv,
    read_products_from_sheets,
    write_image_urls_to_csv,
    write_image_urls_to_sheets,
)
from shopify_fetcher import get_fauno_products

# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Rutas del proyecto
ROOT         = Path(__file__).parent
TEMPLATE     = ROOT / "src" / "template.html"
OUTPUT_DIR   = ROOT / "output" / "images"
FEED_CSV     = ROOT / "output" / "supplemental_feed.csv"
DOCS_DIR     = ROOT / "docs" / "images"   # GitHub Pages sirve desde docs/


def parse_args():
    p = argparse.ArgumentParser(description="Fauno Meta Catalog Overlay Generator")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--shopify",   action="store_true", help="Leer directo de fauno.com.co (recomendado, sin credenciales)")
    src.add_argument("--csv",       metavar="PATH",  help="CSV con productos")
    src.add_argument("--sheet-id",  metavar="ID",    help="ID del Google Sheet")
    p.add_argument("--worksheet",   metavar="NAME",  default=None)
    p.add_argument("--only-sale",   action="store_true", help="Solo productos en oferta")
    p.add_argument("--product-ids", metavar="IDs",   default=None)
    p.add_argument("--dry-run",     action="store_true")
    p.add_argument("--github-push", action="store_true", help="Commit y push a GitHub")
    p.add_argument("--github-repo", metavar="REPO",  default=None,
                   help="user/repo para GitHub Pages (ej: crownmedia/fauno-catalog)")
    p.add_argument("--base-url",    metavar="URL",   default=None,
                   help="URL base donde las imágenes estarán públicas")
    return p.parse_args()


def main():
    args = parse_args()

    # ── 1. Leer productos ──────────────────────────────────────────────────
    logger.info("📥 Leyendo catálogo de productos...")
    if args.shopify:
        products = get_fauno_products()
    elif args.csv:
        products = read_products_from_csv(args.csv)
    else:
        products = read_products_from_sheets(args.sheet_id, args.worksheet)

    logger.info(f"   Total: {len(products)} productos")

    # ── 2. Filtros opcionales ──────────────────────────────────────────────
    if args.only_sale:
        before = len(products)
        products = [
            p for p in products
            if p.get("compare_at_price") and p["compare_at_price"] > p["price"]
        ]
        logger.info(f"   Filtro oferta: {len(products)}/{before} productos en promoción")

    if args.product_ids:
        ids = set(args.product_ids.split(","))
        products = [p for p in products if p["id"] in ids]
        logger.info(f"   Filtro IDs: {len(products)} productos seleccionados")

    if not products:
        logger.warning("⚠️  Sin productos para procesar. Saliendo.")
        return

    # ── 3. Dry run — solo estadísticas ─────────────────────────────────────
    if args.dry_run:
        on_sale = sum(
            1 for p in products
            if p.get("compare_at_price") and p["compare_at_price"] > p["price"]
        )
        logger.info("\n── DRY RUN ─────────────────────────────────────")
        logger.info(f"   Total a procesar:    {len(products)}")
        logger.info(f"   Con oferta activa:   {on_sale}")
        logger.info(f"   Sin oferta:          {len(products) - on_sale}")

        if on_sale:
            max_disc = max(
                round((1 - p["price"] / p["compare_at_price"]) * 100)
                for p in products
                if p.get("compare_at_price") and p["compare_at_price"] > p["price"]
            )
            logger.info(f"   Descuento máximo:    {max_disc}%")
        logger.info("────────────────────────────────────────────────")
        return

    # ── 4. Generar imágenes ─────────────────────────────────────────────────
    logger.info(f"\n🎨 Generando imágenes ({len(products)} productos)...")
    generator = ImageGenerator(
        template_path=TEMPLATE,
        output_dir=OUTPUT_DIR,
    )
    generated = generator.generate_all_sync(products)
    logger.info(f"   ✅ {len(generated)}/{len(products)} imágenes generadas")

    # ── 5. Construir mapa de URLs públicas ──────────────────────────────────
    base_url = args.base_url or _infer_base_url(args.github_repo)
    image_urls: dict[str, str] = {}
    for pid, local_path in generated.items():
        image_urls[pid] = f"{base_url.rstrip('/')}/{local_path.name}"

    # ── 6. Escribir feed suplementario CSV ─────────────────────────────────
    write_image_urls_to_csv(products, image_urls, FEED_CSV)

    # Si hay Sheet ID, también actualizar el Google Sheet
    if args.sheet_id:
        try:
            write_image_urls_to_sheets(args.sheet_id, image_urls)
        except Exception as e:
            logger.warning(f"No se pudo actualizar el Sheet: {e}")
            logger.warning("   El CSV local sí fue generado correctamente.")

    # ── 7. Copiar imágenes a docs/ para GitHub Pages ────────────────────────
    if args.github_push or os.environ.get("GITHUB_ACTIONS"):
        _copy_to_docs(generated)
        if args.github_push:
            _git_commit_and_push()

    # ── 8. Resumen final ────────────────────────────────────────────────────
    on_sale_count = sum(
        1 for p in products
        if p.get("compare_at_price") and p["compare_at_price"] > p["price"]
    )
    logger.info("\n" + "─" * 50)
    logger.info("✅ COMPLETADO")
    logger.info(f"   Imágenes generadas:     {len(generated)}")
    logger.info(f"   Con overlay de oferta:  {on_sale_count}")
    logger.info(f"   Feed CSV:               {FEED_CSV}")
    logger.info(f"   URL base imágenes:      {base_url}")
    logger.info("─" * 50)
    logger.info("\n📋 PRÓXIMO PASO:")
    logger.info("   1. Sube supplemental_feed.csv a una URL pública")
    logger.info("      (o usa GitHub Pages con --github-push)")
    logger.info("   2. En Meta Commerce Manager → Catálogo → Fuentes de datos")
    logger.info("   3. Agregar fuente suplementaria → pega la URL del CSV")
    logger.info("   4. Meta combinará tu feed base de Shopify con estas imágenes")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _infer_base_url(github_repo: str | None) -> str:
    """Construye la URL base de GitHub Pages si se pasa el repo."""
    if github_repo:
        user, repo = github_repo.split("/", 1)
        return f"https://{user}.github.io/{repo}/images"

    # Fallback: URL local (solo para testing)
    return f"file://{OUTPUT_DIR}"


def _copy_to_docs(generated: dict[str, Path]):
    """Copia imágenes a docs/images/ para que GitHub Pages las sirva."""
    import shutil
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    for pid, src in generated.items():
        dst = DOCS_DIR / src.name
        shutil.copy2(src, dst)
    logger.info(f"📁 {len(generated)} imágenes copiadas a docs/images/")


def _git_commit_and_push():
    """Commit y push de las imágenes generadas al repo de GitHub."""
    import subprocess

    def run(cmd: list[str]):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Git error: {result.stderr}")
        return result

    run(["git", "config", "user.name",  "Fauno Catalog Bot"])
    run(["git", "config", "user.email", "bot@crownmedia.com.co"])
    run(["git", "add",    "docs/images/"])
    run(["git", "add",    "output/supplemental_feed.csv"])

    result = run([
        "git", "commit", "-m",
        "chore: actualizar imágenes de catálogo [auto]"
    ])
    if "nothing to commit" in result.stdout:
        logger.info("📝 Sin cambios nuevos en imágenes")
        return

    run(["git", "push"])
    logger.info("🚀 Imágenes publicadas en GitHub Pages")


if __name__ == "__main__":
    main()
