"""
Backend - Dashboard Actividad Económica | Grupo Petersen
Render deployment: Python + Flask
Endpoints:
  GET /api/indicadores      → BCRA + tipo de cambio
  GET /api/noticias         → RSS feeds clasificados por Claude
  GET /api/sectores/<prov>  → Datos sectoriales por provincia
  GET /health               → health check
"""

import os, json, time, logging, hashlib
from datetime import datetime, timedelta
from functools import wraps

import requests
import feedparser
from flask import Flask, jsonify
from flask_cors import CORS
from anthropic import Anthropic

# ── Config ────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, origins=["*"])   # GitHub Pages → Render

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
anthropic_client  = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# ── Cache simple in-memory ────────────────────────────────────────────────────
_cache: dict = {}
CACHE_TTL = {
    "indicadores": 900,    # 15 min
    "noticias":    3600,   # 1 hora
    "sectores":    1800,   # 30 min
}

def cached(key_prefix: str, ttl_key: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            cache_key = f"{key_prefix}:{':'.join(str(a) for a in args)}"
            if cache_key in _cache:
                data, ts = _cache[cache_key]
                if time.time() - ts < CACHE_TTL[ttl_key]:
                    return data
            result = fn(*args, **kwargs)
            _cache[cache_key] = (result, time.time())
            return result
        return wrapper
    return decorator

# ── RSS Feeds por sector ──────────────────────────────────────────────────────
RSS_FEEDS = [
    {"url": "https://www.cronista.com/rss/economia/",        "fuente": "El Cronista"},
    {"url": "https://www.infobae.com/economia/rss/",         "fuente": "Infobae Economía"},
    {"url": "https://www.iprofesional.com/rss",              "fuente": "iProfesional"},
    {"url": "https://www.ambito.com/rss.xml",                "fuente": "Ámbito"},
    {"url": "https://www.agrofy.com.ar/rss",                 "fuente": "Agrofy"},
    {"url": "https://news.google.com/rss/search?q=mineria+argentina&hl=es-419", "fuente": "Google News Minería"},
    {"url": "https://news.google.com/rss/search?q=petroleo+gas+argentina&hl=es-419", "fuente": "Google News Oil&Gas"},
    {"url": "https://news.google.com/rss/search?q=pyme+credito+argentina&hl=es-419", "fuente": "Google News PyME"},
]

SECTORES_KEYWORDS = {
    "agricultura":   ["campo", "soja", "maíz", "trigo", "cosecha", "agro", "granos", "oleaginosa", "cereal"],
    "agroindustria": ["frigorífico", "alimentos", "exportación agroalimentaria", "procesamiento", "frigorífico"],
    "maquinaria":    ["maquinaria agrícola", "cosechadora", "John Deere", "Case", "implemento"],
    "mineria":       ["minería", "oro", "plata", "litio", "cobre", "yacimiento", "extracción mineral"],
    "oil_gas":       ["petróleo", "gas", "YPF", "Vaca Muerta", "offshore", "hidrocarburo", "pozo"],
    "energia":       ["energía renovable", "solar", "eólico", "parque eólico", "paneles solares", "ERNC"],
    "construccion":  ["construcción", "obra pública", "vivienda", "infraestructura", "cemento", "hierro"],
    "comercio":      ["comercio", "ventas minoristas", "consumo", "retail", "supermercado", "facturación"],
    "tecnologia":    ["tecnología", "software", "startup", "fintech", "exportación software", "IT"],
    "turismo":       ["turismo", "hotelería", "gastronomía", "temporada", "visitantes"],
    "pesca":         ["pesca", "langostino", "merluza", "acuicultura", "puerto pesquero"],
    "vitivinicultura": ["vino", "bodega", "uva", "mosto", "vendimia", "exportación vinos"],
}

PROVINCIAS_KEYWORDS = {
    "SF": ["Santa Fe", "Rosario", "Rafaela", "Venado Tuerto"],
    "ER": ["Entre Ríos", "Paraná", "Concordia", "Gualeguaychú"],
    "SJ": ["San Juan", "Ullum", "Jáchal", "Veladero"],
    "SC": ["Santa Cruz", "Río Gallegos", "Caleta Olivia", "Patagonia"],
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_get(url: str, timeout: int = 8, **kwargs) -> dict | None:
    try:
        r = requests.get(url, timeout=timeout, **kwargs)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"safe_get failed {url}: {e}")
        return None


def fetch_bcra_serie(id_variable: int) -> float | None:
    """
    BCRA API pública:
    https://api.bcra.gob.ar/estadisticas/v2.0/principalesvariables
    """
    url = f"https://api.bcra.gob.ar/estadisticas/v2.0/datosvariable/{id_variable}/1/1"
    data = safe_get(url)
    if data and "results" in data and data["results"]:
        return data["results"][0].get("valor")
    return None


def clasificar_noticia_claude(titulo: str, descripcion: str) -> dict:
    """
    Usa Claude Haiku para clasificar una noticia:
    - sector (de SECTORES_KEYWORDS)
    - sentimiento: positivo / negativo / neutro
    - provincias afectadas
    - alerta_temprana: bool
    - resumen_corto: str (max 80 chars)
    """
    if not anthropic_client:
        return {
            "sector": "general", "sentimiento": "neutro",
            "provincias": [], "alerta_temprana": False,
            "resumen_corto": titulo[:80]
        }

    prompt = f"""Sos un analista económico argentino. Clasificá esta noticia en JSON estricto, sin texto extra.

Noticia:
Título: {titulo}
Descripción: {descripcion[:300]}

Respondé SOLO con este JSON:
{{
  "sector": "<uno de: agricultura|agroindustria|maquinaria|mineria|oil_gas|energia|construccion|comercio|tecnologia|turismo|pesca|vitivinicultura|general>",
  "sentimiento": "<positivo|negativo|neutro>",
  "provincias": ["<SF|ER|SJ|SC>"],
  "alerta_temprana": <true si implica riesgo o caída significativa para el sector, false si no>,
  "resumen_corto": "<máximo 80 caracteres, accionable para bancario>"
}}"""

    try:
        resp = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        text = resp.content[0].text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as e:
        log.warning(f"Claude clasificación error: {e}")
        return {
            "sector": "general", "sentimiento": "neutro",
            "provincias": [], "alerta_temprana": False,
            "resumen_corto": titulo[:80]
        }


def tag_noticia_local(titulo: str, descripcion: str) -> dict:
    """Fallback sin Claude: tagging por keywords."""
    texto = (titulo + " " + descripcion).lower()
    sector = "general"
    for s, kws in SECTORES_KEYWORDS.items():
        if any(kw.lower() in texto for kw in kws):
            sector = s
            break

    provincias = [p for p, kws in PROVINCIAS_KEYWORDS.items()
                  if any(kw.lower() in texto for kw in kws)]

    sentimiento = "neutro"
    neg_words = ["caída", "baja", "crisis", "problemas", "cierre", "desempleo", "deuda", "default", "recesión"]
    pos_words = ["crecimiento", "récord", "aumento", "expansión", "inversión", "boom", "mejora", "exportación"]
    if any(w in texto for w in neg_words):
        sentimiento = "negativo"
    elif any(w in texto for w in pos_words):
        sentimiento = "positivo"

    alerta = sentimiento == "negativo" and sector != "general"
    return {
        "sector": sector, "sentimiento": sentimiento,
        "provincias": provincias, "alerta_temprana": alerta,
        "resumen_corto": titulo[:80]
    }

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok", "ts": datetime.utcnow().isoformat()})


@app.route("/api/indicadores")
@cached("indicadores", "indicadores")
def get_indicadores():
    """
    Combina:
    - dolarapi.com → tipos de cambio
    - BCRA API     → tasas e inflación
    """
    result = {"ts": datetime.utcnow().isoformat(), "dolar": {}, "bcra": {}, "error": None}

    # Tipo de cambio
    dolar = safe_get("https://dolarapi.com/v1/dolares")
    if dolar:
        for d in dolar:
            key = d.get("casa", "").lower()
            result["dolar"][key] = {
                "compra": d.get("compra"),
                "venta":  d.get("venta"),
                "nombre": d.get("nombre"),
            }

    # BCRA Variables principales
    # 27 = inflación mensual, 7 = tasa pases pasivos, 6 = tasa badlar, 29 = reservas
    bcra_ids = {
        "inflacion_mensual": 27,
        "tasa_politica":     6,
        "reservas_bn":       1,
        "base_monetaria":    15,
    }
    for nombre, vid in bcra_ids.items():
        val = fetch_bcra_serie(vid)
        if val is not None:
            result["bcra"][nombre] = val

    return result


@app.route("/api/noticias")
@cached("noticias", "noticias")
def get_noticias():
    """
    Lee RSS feeds, clasifica con Claude (o fallback keywords),
    devuelve últimas 40 noticias ordenadas por fecha.
    """
    noticias = []
    seen = set()

    for feed_cfg in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_cfg["url"])
            for entry in feed.entries[:8]:
                titulo     = entry.get("title", "")
                desc       = entry.get("summary", entry.get("description", ""))
                link       = entry.get("link", "")
                pub_parsed = entry.get("published_parsed")
                pub_date   = datetime(*pub_parsed[:6]).isoformat() if pub_parsed else datetime.utcnow().isoformat()

                # Dedup por hash título
                h = hashlib.md5(titulo.encode()).hexdigest()[:8]
                if h in seen:
                    continue
                seen.add(h)

                # Clasificar: Claude si disponible, sino keywords
                if anthropic_client and ANTHROPIC_API_KEY:
                    clasificacion = clasificar_noticia_claude(titulo, desc)
                else:
                    clasificacion = tag_noticia_local(titulo, desc)

                noticias.append({
                    "id":             h,
                    "titulo":         titulo,
                    "descripcion":    desc[:250],
                    "link":           link,
                    "fuente":         feed_cfg["fuente"],
                    "fecha":          pub_date,
                    **clasificacion,
                })
        except Exception as e:
            log.warning(f"RSS error {feed_cfg['url']}: {e}")

    # Ordenar por fecha desc
    noticias.sort(key=lambda x: x["fecha"], reverse=True)
    return {"ts": datetime.utcnow().isoformat(), "total": len(noticias), "items": noticias[:50]}


@app.route("/api/sectores/<prov>")
@cached("sectores", "sectores")
def get_sectores(prov: str):
    """
    Por ahora retorna datos estructurados base.
    Extensible: agregar scraping de IERAL, INDEC, ministerios provinciales.
    """
    prov = prov.upper()
    DATA = {
        "SF": {
            "provincia": "Santa Fe", "var_anual": 4.2, "var_mensual": 0.8,
            "sectores": [
                {"codigo":"A011","nombre":"Agricultura – Cereales y Oleaginosas","varA":6.1,"varM":1.2,"indice":88,"opp":"crecer","size":"mediana"},
                {"codigo":"C261","nombre":"Maquinaria Agrícola","varA":8.4,"varM":2.1,"indice":95,"opp":"crecer","size":"mediana"},
                {"codigo":"C101","nombre":"Frigoríficos y Alimentos","varA":5.8,"varM":1.5,"indice":92,"opp":"crecer","size":"mediana"},
                {"codigo":"J620","nombre":"Servicios Tecnológicos","varA":11.2,"varM":2.8,"indice":43,"opp":"crecer","size":"pequena"},
                {"codigo":"G461","nombre":"Comercio Mayorista Agro","varA":4.7,"varM":0.9,"indice":78,"opp":"crecer","size":"pequena"},
                {"codigo":"C241","nombre":"Metalmecánica","varA":3.1,"varM":0.6,"indice":71,"opp":"defender","size":"mediana"},
                {"codigo":"A012","nombre":"Horticultura","varA":2.4,"varM":0.3,"indice":45,"opp":"defender","size":"pequena"},
                {"codigo":"H491","nombre":"Transporte de Cargas","varA":0.9,"varM":0.2,"indice":62,"opp":"observar","size":"pequena"},
                {"codigo":"I551","nombre":"Hotelería y Gastronomía","varA":1.2,"varM":0.3,"indice":38,"opp":"observar","size":"micro"},
                {"codigo":"G471","nombre":"Comercio Minorista","varA":-1.8,"varM":-0.4,"indice":55,"opp":"salir","size":"micro"},
                {"codigo":"C131","nombre":"Industria Textil","varA":-3.2,"varM":-0.7,"indice":34,"opp":"salir","size":"pequena"},
                {"codigo":"F411","nombre":"Construcción Residencial","varA":-5.1,"varM":-1.2,"indice":40,"opp":"salir","size":"pequena"},
            ]
        },
        "ER": {
            "provincia": "Entre Ríos", "var_anual": 2.1, "var_mensual": -0.3,
            "sectores": [
                {"codigo":"A022","nombre":"Avicultura","varA":7.8,"varM":1.9,"indice":90,"opp":"crecer","size":"mediana"},
                {"codigo":"I551","nombre":"Turismo Termal","varA":9.1,"varM":2.2,"indice":65,"opp":"crecer","size":"pequena"},
                {"codigo":"C101","nombre":"Industria Avícola","varA":6.9,"varM":1.4,"indice":88,"opp":"crecer","size":"mediana"},
                {"codigo":"A011","nombre":"Agricultura – Cereales","varA":5.2,"varM":0.8,"indice":82,"opp":"crecer","size":"mediana"},
                {"codigo":"A031","nombre":"Pesca Continental","varA":3.4,"varM":0.5,"indice":48,"opp":"defender","size":"pequena"},
                {"codigo":"F411","nombre":"Obras Públicas","varA":4.2,"varM":0.7,"indice":58,"opp":"defender","size":"pequena"},
                {"codigo":"C241","nombre":"Metalmecánica","varA":0.8,"varM":0.1,"indice":51,"opp":"observar","size":"pequena"},
                {"codigo":"H491","nombre":"Transporte y Logística","varA":1.1,"varM":0.2,"indice":55,"opp":"observar","size":"pequena"},
                {"codigo":"G471","nombre":"Comercio Minorista","varA":-2.4,"varM":-0.6,"indice":48,"opp":"salir","size":"micro"},
                {"codigo":"C161","nombre":"Industria Forestal","varA":-2.1,"varM":-0.5,"indice":42,"opp":"salir","size":"pequena"},
            ]
        },
        "SJ": {
            "provincia": "San Juan", "var_anual": 1.4, "var_mensual": 0.5,
            "sectores": [
                {"codigo":"D351","nombre":"Energía Solar y Renovable","varA":15.4,"varM":3.8,"indice":42,"opp":"crecer","size":"pequena"},
                {"codigo":"B051","nombre":"Minería – Oro y Plata","varA":12.3,"varM":3.1,"indice":95,"opp":"crecer","size":"mediana"},
                {"codigo":"B091","nombre":"Servicios a la Minería","varA":8.1,"varM":1.8,"indice":72,"opp":"crecer","size":"mediana"},
                {"codigo":"A013","nombre":"Olivicultura","varA":6.8,"varM":1.5,"indice":55,"opp":"crecer","size":"pequena"},
                {"codigo":"C110","nombre":"Elaboración de Vinos","varA":5.2,"varM":1.1,"indice":74,"opp":"crecer","size":"mediana"},
                {"codigo":"F411","nombre":"Construcción Minera","varA":7.2,"varM":1.6,"indice":65,"opp":"crecer","size":"pequena"},
                {"codigo":"A011","nombre":"Vitivinicultura","varA":3.6,"varM":0.7,"indice":68,"opp":"defender","size":"pequena"},
                {"codigo":"I551","nombre":"Turismo Aventura","varA":4.8,"varM":1.0,"indice":38,"opp":"defender","size":"micro"},
                {"codigo":"G471","nombre":"Comercio Minorista","varA":-1.2,"varM":-0.3,"indice":44,"opp":"observar","size":"micro"},
                {"codigo":"C241","nombre":"Minero-Metalurgia","varA":-3.8,"varM":-0.8,"indice":35,"opp":"salir","size":"pequena"},
            ]
        },
        "SC": {
            "provincia": "Santa Cruz", "var_anual": 3.8, "var_mensual": 1.1,
            "sectores": [
                {"codigo":"D351","nombre":"Energía Eólica y Renovable","varA":18.6,"varM":4.2,"indice":58,"opp":"crecer","size":"pequena"},
                {"codigo":"B091","nombre":"Servicios Oil & Gas","varA":10.2,"varM":2.5,"indice":85,"opp":"crecer","size":"mediana"},
                {"codigo":"B060","nombre":"Extracción Petróleo y Gas","varA":8.7,"varM":2.1,"indice":98,"opp":"crecer","size":"mediana"},
                {"codigo":"H491","nombre":"Logística Oil & Gas","varA":7.8,"varM":1.9,"indice":68,"opp":"crecer","size":"pequena"},
                {"codigo":"I551","nombre":"Turismo Glaciares","varA":6.2,"varM":1.4,"indice":52,"opp":"crecer","size":"micro"},
                {"codigo":"F421","nombre":"Construcción Infraestructura","varA":5.9,"varM":1.3,"indice":70,"opp":"crecer","size":"pequena"},
                {"codigo":"A031","nombre":"Pesca Marítima","varA":4.1,"varM":0.8,"indice":72,"opp":"defender","size":"mediana"},
                {"codigo":"C101","nombre":"Procesamiento de Pescado","varA":3.8,"varM":0.7,"indice":65,"opp":"defender","size":"mediana"},
                {"codigo":"A014","nombre":"Ganadería Ovina","varA":-1.4,"varM":-0.3,"indice":45,"opp":"observar","size":"pequena"},
                {"codigo":"G471","nombre":"Comercio Minorista","varA":-0.8,"varM":-0.2,"indice":42,"opp":"observar","size":"micro"},
            ]
        }
    }

    if prov not in DATA:
        return jsonify({"error": f"Provincia {prov} no encontrada"}), 404

    return {"ts": datetime.utcnow().isoformat(), **DATA[prov]}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
