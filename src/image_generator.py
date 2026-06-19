"""
image_generator.py — Genera imágenes de catálogo usando Playwright

Playwright abre el template HTML en un browser headless, inyecta los datos
del producto, espera a que el canvas renderice y hace screenshot.

Requiere: pip install playwright && playwright install chromium
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

LOGO_URL = (
    "https://cdn.shopify.com/s/files/1/0272/3908/8189/files/"
    "26A759F5-6D12-4B55-8883-214293ADA1FA_-Photoroom.png"
)
FREE_SHIPPING_THRESHOLD = 149_900  # COP


class ImageGenerator:
    """Genera imágenes de producto con overlays de marca para Meta Catalog."""

    def __init__(
        self,
        template_path: Path,
        output_dir: Path,
        logo_url: str = LOGO_URL,
        canvas_size: int = 500,
        benefits_map: dict[str, list[str]] | None = None,
    ):
        self.template_path = Path(template_path)
        self.output_dir = Path(output_dir)
        self.logo_url = logo_url
        self.canvas_size = canvas_size
        self.benefits_map: dict[str, list[str]] = benefits_map or {}
        self.output_dir.mkdir(parents=True, exist_ok=True)

        if not self.template_path.exists():
            raise FileNotFoundError(f"Template no encontrado: {self.template_path}")

    # ─────────────────────────────────────────────────────────────────────────
    # API pública
    # ─────────────────────────────────────────────────────────────────────────

    async def generate_all(self, products: list[dict]) -> dict[str, Path]:
        """
        Genera imágenes para todos los productos.
        Retorna {product_id: ruta_imagen}
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            context = await browser.new_context(
                viewport={"width": self.canvas_size, "height": self.canvas_size},
                device_scale_factor=1,
            )
            page = await context.new_page()

            results: dict[str, Path] = {}
            for i, product in enumerate(products):
                pid = product.get("id", f"product_{i}")
                try:
                    path = await self._generate_one(page, product)
                    results[pid] = path
                    logger.info(f"✅ [{i+1}/{len(products)}] {product.get('title', pid)}")
                except Exception as e:
                    logger.error(f"❌ [{i+1}/{len(products)}] {pid}: {e}")

            await browser.close()

        return results

    def generate_all_sync(self, products: list[dict]) -> dict[str, Path]:
        """Versión síncrona para usar sin event loop."""
        return asyncio.run(self.generate_all(products))

    # ─────────────────────────────────────────────────────────────────────────
    # Interno
    # ─────────────────────────────────────────────────────────────────────────

    async def _generate_one(self, page, product: dict) -> Path:
        """Renderiza un producto y retorna la ruta de la imagen guardada."""
        data = self._build_render_data(product)
        output_path = self.output_dir / f"{product['id']}.jpg"

        # Navegar al template (file:// URL)
        template_url = self.template_path.resolve().as_uri()
        await page.goto(template_url, wait_until="domcontentloaded")

        # Inyectar datos y ejecutar renderProduct()
        await page.evaluate(
            """(data) => {
                window.__RENDER_COMPLETE__ = false;
                window.PRODUCT_DATA = data;
                return renderProduct(data);
            }""",
            data,
        )

        # Esperar a que el canvas termine (máx 15 segundos)
        await page.wait_for_function(
            "() => window.__RENDER_COMPLETE__ === true",
            timeout=15_000,
        )

        # Screenshot del contenedor principal (div#container, HTML/CSS layout)
        container_el = await page.query_selector("div#container")
        if not container_el:
            raise RuntimeError("div#container no encontrado en el template")

        await container_el.screenshot(path=str(output_path), type="jpeg", quality=92)
        return output_path

    def _build_render_data(self, product: dict) -> dict:
        """Transforma un dict de producto al formato que espera el template."""
        price = float(product.get("price") or 0)
        compare_at = product.get("compare_at_price")
        compare_at = float(compare_at) if compare_at else None

        # Separar título de la presentación (ej: "Shampoo Sin Sulfatos 400ml" → title + subtitle)
        raw_title = product.get("title", "")
        title, subtitle = self._split_title(raw_title)

        # Beneficios: sheet por handle/id → por colección → defaults
        benefits = self._get_benefits(product, self.benefits_map)

        # Etiqueta dinámica (se ignora si hay oferta — el badge tiene prioridad)
        label = self._get_label(product, price)

        # Envío gratis si el precio supera el umbral
        free_shipping = price >= FREE_SHIPPING_THRESHOLD

        return {
            "title": title,
            "subtitle": subtitle,
            "price": price,
            "compare_at_price": compare_at,
            "image_url": product.get("image_link", ""),
            "logo_url": self.logo_url,
            "benefits": benefits,
            "label": label,
            "free_shipping": free_shipping,
        }

    # ─── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _split_title(title: str) -> tuple[str, str]:
        """
        Separa volumen/presentación del título principal.
        "Shampoo Sin Sulfatos 400ml" → ("Shampoo Sin Sulfatos", "400ml")
        """
        import re
        # Busca patrones tipo: 400ml, 200g, 2x300ml, 1L, etc.
        m = re.search(r'(\d+\s*(?:ml|g|gr|L|oz|x\d+\s*ml))\s*$', title, re.I)
        if m:
            subtitle = m.group(0).strip()
            main = title[:m.start()].strip()
            return main, subtitle
        return title, ""

    @staticmethod
    def _get_benefits(product: dict, benefits_map: dict[str, list[str]] | None = None) -> list[str]:
        """
        Orden de prioridad:
        1. benefits_map por handle/id (cargado desde Google Sheets)
        2. product["benefits"] (campo directo en el producto)
        3. benefits_map por colección (config interna)
        4. Defaults
        """
        # 1. Buscar en el mapa de beneficios por handle o id
        if benefits_map:
            handle = (product.get("handle") or "").lower().strip()
            pid = str(product.get("id") or "").lower().strip()
            custom = benefits_map.get(handle) or benefits_map.get(pid)
            if custom:
                return custom

        # 2. Campo directo en el producto
        if product.get("benefits"):
            b = product["benefits"]
            return b if isinstance(b, list) else [x.strip() for x in b.split(",")]

        COLLECTION_BENEFITS = {
            "cuidado-capilar":         ["Sin Sulfatos", "Sin Parabenos", "Vegano"],
            "shampoo":                 ["Sin Sulfatos", "pH Balanceado", "Vegano"],
            "tratamientos-capilares":  ["Tecnología Plex", "Sin Parabenos", "Restaura el daño"],
            "mascarillas-capilares":   ["Nutrición Profunda", "Sin Parabenos", "Cruelty-free"],
            "cuidado-facial":          ["Sin Parabenos", "Vegano", "Derm. Testeado"],
            "proteccion-solar":        ["FPS 50+", "Sin Parabenos", "Resist. al agua"],
            "ninos-y-bebes":           ["Fórmula Suave", "Sin Lágrimas", "Cruelty-free"],
            "rutinas-y-kits-capilares":["Rutina Completa", "Sin Sulfatos", "Plex Tech"],
            "rutinas-y-kits-faciales": ["Rutina Completa", "Ing. Naturales", "Vegano"],
            "tratamientos-y-serums":   ["Alta Concentración", "Sin Parabenos", "Resultados rápidos"],
        }

        collection = (product.get("product_type") or "").lower().replace(" ", "-")
        for key, benefits in COLLECTION_BENEFITS.items():
            if key in collection:
                return benefits

        return ["Sin Parabenos", "Vegano", "Cruelty-free"]

    @staticmethod
    def _get_label(product: dict, price: float) -> Optional[str]:
        """Determina la etiqueta dinámica del producto."""
        # Etiqueta explícita en los datos
        if product.get("label"):
            return product["label"]

        # "Nuevo" si fue publicado hace menos de 30 días
        from datetime import datetime, timezone, timedelta
        published = product.get("published_at")
        if published:
            try:
                if isinstance(published, str):
                    dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                else:
                    dt = published
                cutoff = datetime.now(timezone.utc) - timedelta(days=30)
                if dt > cutoff:
                    return "nuevo"
            except (ValueError, TypeError):
                pass

        # "Top Ventas" si hay ranking de ventas
        if product.get("is_top_seller"):
            return "top_ventas"

        return None
