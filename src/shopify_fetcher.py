"""
shopify_fetcher.py — Lee el catálogo completo de Fauno desde el endpoint público de Shopify

No requiere credenciales. Usa la API pública de storefronts que Shopify expone.
URL: https://fauno.com.co/collections/all/products.json

Campos extraídos:
  id, title, price, compare_at_price, image_link, published_at, tags, available
"""

import logging
import time
import urllib.request
import json

logger = logging.getLogger(__name__)

# Handles exactos de los productos "Top en ventas" — actualizar según indicación del cliente
TOP_SELLER_HANDLES = {
    "alisador-progresivo-termoprotectors",          # Alisador Progresivo Termoprotector 400ml
    "serum-anti-edad-vitamina-c-acido-ferulico-30ml",  # Serum Anti-Edad Vitamina C Ácido Ferúlico
    "crema-hidra-gel-24h-50gr",                     # Crema Hidra Gel 24h 50gr
    "oleo-capilar",                                 # Óleo Capilar
    "spray-anti-humedad-desenredante",              # Spray Anti-Frizz
}

# También detectar por tag como fallback
TOP_SELLER_TAGS = {"lo más vendido", "lo mas vendido", "top en ventas", "top ventas", "best seller"}
FREE_SHIPPING_THRESHOLD = 149_900  # COP


def fetch_all_products(store_url: str = "https://fauno.com.co") -> list[dict]:
    """
    Descarga todos los productos activos del store Shopify.
    Pagina automáticamente hasta obtener todos.
    """
    all_products = []
    page = 1
    limit = 250

    while True:
        url = f"{store_url.rstrip('/')}/collections/all/products.json?limit={limit}&page={page}"
        logger.info(f"   Fetching página {page}... ({url})")

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "FaunoCatalogBot/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.error(f"Error descargando página {page}: {e}")
            break

        products = data.get("products", [])
        if not products:
            break

        all_products.extend(products)
        logger.info(f"   Página {page}: {len(products)} productos (total: {len(all_products)})")

        if len(products) < limit:
            break  # Última página

        page += 1
        time.sleep(0.5)  # respetar rate limits

    return all_products


def normalize_products(raw_products: list[dict]) -> list[dict]:
    """
    Transforma los productos del formato Shopify JSON al formato estándar del sistema.
    Filtra productos sin stock o sin imagen.
    """
    normalized = []

    for p in raw_products:
        # Solo productos publicados y con al menos una variante disponible
        variants = p.get("variants", [])
        if not variants:
            continue

        variant = variants[0]  # Usamos la primera variante (la principal)
        if not variant.get("available", False):
            continue  # Sin stock

        images = p.get("images", [])
        if not images:
            continue  # Sin imagen

        # Precio
        try:
            price = float(variant.get("price") or 0)
        except (ValueError, TypeError):
            continue

        try:
            compare_raw = float(variant.get("compare_at_price") or 0)
            compare_at = compare_raw if compare_raw > price else None
        except (ValueError, TypeError):
            compare_at = None

        # Tags → detectar Top Ventas (handle exacto tiene prioridad, tags como fallback)
        tags = [t.lower().strip() for t in p.get("tags", [])]
        handle = p.get("handle", "").lower().strip()
        is_top_seller = (
            handle in TOP_SELLER_HANDLES
            or any(t in TOP_SELLER_TAGS for t in tags)
        )

        # Colección/tipo desde tags
        product_type = _infer_type_from_tags(tags)

        normalized.append({
            "id":               str(p["id"]),
            "title":            p.get("title", "").strip(),
            "handle":           p.get("handle", ""),
            "price":            price,
            "compare_at_price": compare_at,
            "image_link":       images[0]["src"],
            "product_type":     product_type,
            "published_at":     p.get("published_at", ""),
            "is_top_seller":    is_top_seller,
            "tags":             tags,
            "label":            "top_ventas" if is_top_seller else None,
            "benefits":         None,  # se asigna por colección en image_generator
            "availability":     "in stock",
        })

    logger.info(f"✅ {len(normalized)} productos activos con imagen (de {len(raw_products)} totales)")
    return normalized


def _infer_type_from_tags(tags: list[str]) -> str:
    """Infiere la colección del producto desde sus tags."""
    TAG_TO_COLLECTION = {
        "capilar":    "cuidado-capilar",
        "shampoo":    "shampoo",
        "rizos":      "cuidado-capilar",
        "plex":       "tratamientos-capilares",
        "mascarilla": "mascarillas-capilares",
        "facial":     "cuidado-facial",
        "solar":      "proteccion-solar",
        "baby":       "ninos-y-bebes",
        "corporal":   "cuidado-corporal",
        "ecorefill":  "cuidado-capilar",
    }
    for tag in tags:
        for keyword, collection in TAG_TO_COLLECTION.items():
            if keyword in tag:
                return collection
    return ""


def get_fauno_products() -> list[dict]:
    """Función principal: descarga y normaliza el catálogo completo de Fauno."""
    logger.info("🛍️  Descargando catálogo de Fauno...")
    raw = fetch_all_products("https://fauno.com.co")
    return normalize_products(raw)
