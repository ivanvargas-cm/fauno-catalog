# Setup — Fauno Meta Catalog Overlay

## Qué hace este sistema

1. Lee el catálogo de Fauno desde un Google Sheet de Dataslayer
2. Genera una imagen con overlay (logo, beneficios, precio, etiqueta) por cada producto
3. Sube las imágenes a GitHub Pages (gratis, públicas)
4. Actualiza un feed CSV que Meta Commerce Manager lee para usar esas imágenes en tus campañas de catálogo

---

## Paso 1 — Configurar el repositorio GitHub

1. Crea un repo en GitHub: `crownmedia/fauno-catalog` (puede ser privado)
2. En Settings → Pages → Source: selecciona **Deploy from branch** → rama `main` → carpeta `/docs`
3. Anota la URL que te da GitHub Pages: `https://crownmedia.github.io/fauno-catalog`

---

## Paso 2 — Google Sheet con datos de Dataslayer

El sheet que Dataslayer sincroniza con Shopify debe tener estas columnas:

| Columna | Descripción |
|---------|-------------|
| `id` | ID del producto en Shopify |
| `title` | Nombre del producto |
| `price` | Precio regular (COP, número) |
| `compare_at_price` | Precio original cuando hay oferta |
| `image_link` | URL de la imagen del producto |
| `product_type` | Colección/categoría |
| `published_at` | Fecha de publicación |
| `label` | (Opcional) `top_ventas`, `nuevo`, `exclusivo_online` |

Anota el **ID del Sheet** (está en la URL: `docs.google.com/spreadsheets/d/**{SHEET_ID}**/...`)

---

## Paso 3 — Google Service Account

Para que el script pueda leer y actualizar el Sheet:

1. Ve a [console.cloud.google.com](https://console.cloud.google.com)
2. Crea un proyecto o usa uno existente
3. Activa la API: **Google Sheets API** y **Google Drive API**
4. Crea un **Service Account**: IAM → Service Accounts → Create
5. Descarga el JSON de credenciales
6. Comparte tu Google Sheet con el email del service account (editor)

---

## Paso 4 — Configurar secrets en GitHub

En tu repo GitHub → Settings → Secrets and variables:

**Secrets:**
- `GOOGLE_SERVICE_ACCOUNT_JSON` → pega todo el contenido del JSON de credenciales

**Variables (Actions):**
- `DATASLAYER_SHEET_ID` → el ID de tu Sheet de Dataslayer

---

## Paso 5 — Configurar Meta Commerce Manager

Una vez que el workflow corra por primera vez y genere el CSV:

1. Ve a Meta Business Suite → Commerce Manager → tu catálogo
2. **Fuentes de datos** → **Agregar fuente suplementaria**
3. URL del feed: `https://crownmedia.github.io/fauno-catalog/supplemental_feed.csv`
   *(ajusta al nombre de tu repo)*
4. Frecuencia: **Horaria** (Meta actualizará cada hora automáticamente)
5. Meta combinará tu feed base de Shopify con las imágenes personalizadas

---

## Uso manual (sin GitHub Actions)

```bash
cd fauno-meta-catalog

# Instalar dependencias
pip install -r requirements.txt
playwright install chromium

# Probar con CSV exportado de Dataslayer
python main.py --csv mis_productos.csv --base-url https://crownmedia.github.io/fauno-catalog

# Con Google Sheets directamente
export GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
python main.py --sheet-id TU_SHEET_ID --base-url https://crownmedia.github.io/fauno-catalog

# Solo productos en oferta
python main.py --csv productos.csv --only-sale --base-url https://...

# Dry run (estadísticas sin generar imágenes)
python main.py --csv productos.csv --dry-run
```

---

## Estructura de archivos generados

```
fauno-meta-catalog/
├── output/
│   ├── images/           ← Imágenes locales generadas
│   │   ├── 8327465123.jpg
│   │   └── ...
│   └── supplemental_feed.csv  ← Feed para Meta (id + image_link)
└── docs/
    └── images/           ← Copia para GitHub Pages (público)
        ├── 8327465123.jpg
        └── ...
```

---

## Troubleshooting

**El script no encuentra el template:**
→ Asegúrate de correr `python main.py` desde la carpeta `fauno-meta-catalog/`

**Error de CORS al cargar imágenes en el browser:**
→ Playwright usa `--no-sandbox` que permite cross-origin. Si persiste, pre-descarga las imágenes manualmente.

**Meta no acepta el CSV:**
→ Verifica que la columna `id` coincida exactamente con los IDs en tu feed base de Shopify.
→ El sheet debe estar publicado como CSV: Archivo → Publicar en la web → CSV

**GitHub Actions falla en el push:**
→ Verifica que el workflow tenga `permissions: contents: write`
