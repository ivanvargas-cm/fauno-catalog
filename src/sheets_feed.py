"""
sheets_feed.py — Lee productos desde Google Sheets (Dataslayer) y escribe URLs generadas

Dos modos:
  1. CSV mode (default): lee un CSV exportado de Dataslayer / Google Sheets
  2. API mode:           usa gspread para leer/escribir directamente en el Sheet

El Sheet de Dataslayer debe tener estas columnas mínimas:
  id, title, price, compare_at_price, image_link, product_type, published_at

Después de generar imágenes, el script escribe en la columna 'generated_image_link'
con la URL pública de GitHub Pages.
"""

import csv
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Lector CSV (modo simple, sin credenciales)
# ─────────────────────────────────────────────────────────────────────────────

def read_products_from_csv(csv_path: str | Path) -> list[dict]:
    """
    Lee productos de un CSV exportado de Dataslayer o Google Sheets.
    Compatible con el formato de exportación de Shopify via Dataslayer.
    """
    products = []
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV no encontrado: {path}")

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            product = _normalize_product(row)
            if product:
                products.append(product)

    logger.info(f"📦 {len(products)} productos leídos desde {path.name}")
    return products


def _normalize_product(row: dict) -> Optional[dict]:
    """Normaliza una fila del CSV al formato estándar del sistema."""
    # Shopify Dataslayer puede exportar con diferentes nombres de columna
    def get(keys: list[str], default=""):
        for k in keys:
            if k in row and row[k] not in ("", None):
                return row[k]
        return default

    product_id = get(["id", "ID", "product_id", "Variant ID"])
    if not product_id:
        return None

    price_raw = get(["price", "Price", "Precio", "Variant Price"])
    compare_raw = get(["compare_at_price", "Compare At Price", "Original Price"])

    try:
        price = float(str(price_raw).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        price = 0.0

    try:
        compare_at = float(str(compare_raw).replace(",", "").replace("$", "").strip())
        if compare_at <= price:
            compare_at = None  # no es una oferta real
    except (ValueError, TypeError):
        compare_at = None

    image_link = get(["image_link", "Image Src", "image_src", "Image URL", "Imagen"])

    # Disponibilidad — saltar productos sin stock o sin imagen
    availability = get(["availability", "Status", "Published"]).lower()
    if availability in ("false", "draft", "archived", "0"):
        return None
    if not image_link:
        return None

    return {
        "id":              str(product_id),
        "title":           get(["title", "Title", "Nombre", "Name"]),
        "handle":          get(["handle", "URL handle"]),
        "price":           price,
        "compare_at_price": compare_at,
        "image_link":      image_link,
        "product_type":    get(["product_type", "Type", "Vendor", "Category", "Colección"]),
        "published_at":    get(["published_at", "Published At", "Created At"]),
        "label":           get(["label", "Label"]) or None,
        "benefits":        get(["benefits", "Benefits", "Claims"]) or None,
        "is_top_seller":   get(["is_top_seller", "Top Seller", "best_seller"]) in ("1", "true", "True", "yes"),
        "availability":    "in stock",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Lector via Google Sheets API (requiere gspread + service account)
# ─────────────────────────────────────────────────────────────────────────────

def read_products_from_sheets(sheet_id: str, worksheet_name: str = None) -> list[dict]:
    """
    Lee productos directamente de Google Sheets via gspread.

    Prerequisitos:
      pip install gspread
      Crear service account en Google Cloud Console
      Compartir el sheet con el email del service account
      Guardar credentials JSON como GOOGLE_SERVICE_ACCOUNT_JSON env var
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise ImportError("Instala: pip install gspread google-auth")

    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        raise ValueError(
            "Variable de entorno GOOGLE_SERVICE_ACCOUNT_JSON no configurada.\n"
            "Exporta las credenciales del service account como JSON string."
        )

    creds_dict = json.loads(creds_json)
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    spreadsheet = client.open_by_key(sheet_id)
    worksheet = (
        spreadsheet.worksheet(worksheet_name)
        if worksheet_name
        else spreadsheet.get_worksheet(0)
    )

    rows = worksheet.get_all_records()
    products = []
    for row in rows:
        product = _normalize_product(row)
        if product:
            products.append(product)

    logger.info(f"📦 {len(products)} productos leídos desde Google Sheets ({sheet_id})")
    return products


# ─────────────────────────────────────────────────────────────────────────────
# Escritura de URLs generadas al Sheet / CSV
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Lector de beneficios por producto desde Google Sheets
# ─────────────────────────────────────────────────────────────────────────────

def read_benefits_from_sheets(
    sheet_id: str,
    worksheet_name: str = "Beneficios",
) -> dict[str, list[str]]:
    """
    Lee un sheet con beneficios por producto y retorna un dict {handle: [b1, b2, b3]}.

    Estructura del sheet (pestaña "Beneficios"):
      | handle                  | benefit_1      | benefit_2    | benefit_3    |
      | shampoo-sin-sulfatos    | Sin Sulfatos   | pH Balanceado| Vegano       |
      | mascarilla-plex         | Tecnología Plex| Sin Parabenos| Restaura daño|

    También acepta columna 'id' como clave alternativa.
    Si una celda está vacía, la ignora.
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise ImportError("Instala: pip install gspread google-auth")

    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON no configurada")

    creds_dict = json.loads(creds_json)
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    ss = client.open_by_key(sheet_id)
    try:
        ws = ss.worksheet(worksheet_name)
    except Exception:
        logger.warning(f"Pestaña '{worksheet_name}' no encontrada en el sheet {sheet_id}")
        return {}

    rows = ws.get_all_records()
    benefits_map: dict[str, list[str]] = {}

    for row in rows:
        # Clave: handle o id
        key = (row.get("handle") or row.get("id") or "").strip().lower()
        if not key:
            continue

        # Recoger benefit_1, benefit_2, benefit_3 (ignorar vacíos)
        benefits = [
            str(row.get(f"benefit_{i}", "")).strip()
            for i in range(1, 4)
            if str(row.get(f"benefit_{i}", "")).strip()
        ]

        # También acepta columna 'benefits' con valores separados por coma
        if not benefits and row.get("benefits"):
            benefits = [b.strip() for b in str(row["benefits"]).split(",") if b.strip()]

        if benefits:
            benefits_map[key] = benefits

    logger.info(f"📋 {len(benefits_map)} productos con beneficios personalizados cargados")
    return benefits_map


def read_benefits_from_csv(csv_path: str | Path) -> dict[str, list[str]]:
    """
    Lee beneficios desde un CSV local (alternativa sin Google Sheets API).

    Formato:
      handle,benefit_1,benefit_2,benefit_3
      shampoo-sin-sulfatos,Sin Sulfatos,pH Balanceado,Vegano
    """
    path = Path(csv_path)
    if not path.exists():
        logger.warning(f"CSV de beneficios no encontrado: {path}")
        return {}

    benefits_map: dict[str, list[str]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row.get("handle") or row.get("id") or "").strip().lower()
            if not key:
                continue
            benefits = [
                row.get(f"benefit_{i}", "").strip()
                for i in range(1, 4)
                if row.get(f"benefit_{i}", "").strip()
            ]
            if not benefits and row.get("benefits"):
                benefits = [b.strip() for b in row["benefits"].split(",") if b.strip()]
            if benefits:
                benefits_map[key] = benefits

    logger.info(f"📋 {len(benefits_map)} productos con beneficios desde CSV")
    return benefits_map


def write_image_urls_to_csv(
    products: list[dict],
    image_urls: dict[str, str],
    output_path: str | Path,
):
    """
    Genera el feed suplementario como CSV para subir a Meta.

    Formato Meta Commerce Manager supplemental feed (CSV):
      id, image_link
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "image_link"])
        for product in products:
            pid = product["id"]
            if pid in image_urls:
                writer.writerow([pid, image_urls[pid]])

    count = sum(1 for p in products if p["id"] in image_urls)
    logger.info(f"📄 Feed suplementario CSV: {output_path} ({count} productos)")


def write_image_urls_to_sheets(
    sheet_id: str,
    image_urls: dict[str, str],
    supplemental_sheet_name: str = "Supplemental Feed",
):
    """
    Actualiza un worksheet con el feed suplementario (id + image_link).
    El sheet debe estar publicado como CSV para que Meta lo pueda leer.
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise ImportError("Instala: pip install gspread google-auth")

    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON no configurada")

    creds_dict = json.loads(creds_json)
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    ss = client.open_by_key(sheet_id)

    # Crear o limpiar el worksheet de supplemental feed
    try:
        ws = ss.worksheet(supplemental_sheet_name)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=supplemental_sheet_name, rows=1000, cols=2)

    # Escribir encabezados + datos
    rows = [["id", "image_link"]] + [
        [pid, url] for pid, url in image_urls.items()
    ]
    ws.update("A1", rows)

    logger.info(
        f"✅ Sheet '{supplemental_sheet_name}' actualizado con {len(image_urls)} productos"
    )
    logger.info(
        f"   Publica el sheet como CSV y usa esa URL en Meta Commerce Manager"
    )
