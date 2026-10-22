"""
datos_externos.py — Módulo de datos reales para ECO RADAR
Integra: datos.gob.ar (mora, cemento, EMI, EMAE) + BCRA API extra
Cachea en memoria 24hs para no martillar las APIs en cada request.

INSTALACIÓN: solo requiere `requests` (ya en cualquier Flask/FastAPI setup)

USO en tu app principal:
    from datos_externos import get_indicadores_ext

    @app.route("/api/indicadores-ext")
    def indicadores_ext():
        return jsonify(get_indicadores_ext())

    @app.route("/api/ping")          # ← también agregá este
    def ping():
        return jsonify({"ok": True})
"""

import requests
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ─── CACHÉ EN MEMORIA ────────────────────────────────────────────────────────
_cache = {}
CACHE_TTL = 60 * 60 * 24  # 24 horas

def _cached(key, fn):
    """Ejecuta fn() y cachea el resultado TTL segundos."""
    now = time.time()
    if key in _cache:
        data, ts = _cache[key]
        if now - ts < CACHE_TTL:
            return data
    try:
        data = fn()
        if data is not None:
            _cache[key] = (data, now)
        return data
    except Exception as e:
        logger.warning(f"[datos_ext] error en {key}: {e}")
        # Si hay cache vieja, devolvela igual (mejor dato viejo que nada)
        if key in _cache:
            return _cache[key][0]
        return None


# ─── CLIENTE HTTP SIMPLE ──────────────────────────────────────────────────────
HEADERS = {"User-Agent": "EcoRadar/1.0 (Grupo Petersen; contacto@bsf.com.ar)"}
TIMEOUT = 12

def _get(url, params=None):
    r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# ─── DATOS.GOB.AR — Series de Tiempo ─────────────────────────────────────────
BASE_ST = "https://apis.datos.gob.ar/series/api/series/"

SERIES = {
    # Mora / Irregularidad (en millones de pesos — necesitamos dos para calcular %)
    "irreg_sistema":   "332.2_SISTEMA_FIADA__53",   # cartera irregular total sistema
    "irreg_privados":  "332.2_BANCOS_PRIADA__51",   # cartera irregular privados

    # Cartera total (para calcular el ratio de mora en %)
    "cartera_sistema": "330.2_SISTEMA_FTOT__53",    # cartera total sistema financiero
    "cartera_priv":    "330.2_BANCOS_PRITOT__51",   # cartera total privados

    # Señales adelantadas
    "cemento_ipi":    "453.2_CEMENTONTO_0_0_7_59",  # IPI cemento (índice mensual)

    # EMI — Estimador Mensual Industrial (nivel general)
    "emi_general":    "11.3_IM_2004_M_15",           # EMI nivel general base 2004

    # EMAE — Actividad Económica nivel general
    "emae_general":   "11.3_VMATC_2004_M_12",        # EMAE nivel general mensual

    # Tasas (datos.gob.ar replica BCRA)
    "tasa_pf_30":     "174.1_T_DEPOPLA_0_0_37",      # Tasa depósitos PF 30d
    "tasa_activa_1l": "174.1_T_INTERO_I_0_0_57",     # Tasa activa empresas 1a línea
}

def _fetch_series(ids: list, limit=2) -> dict:
    """
    Trae los últimos `limit` registros de varias series en un solo call.
    Devuelve dict {serie_id: [val_ultimo, val_anterior]} o None si falla.
    """
    ids_str = ",".join(ids)
    try:
        data = _get(BASE_ST, params={
            "ids": ids_str,
            "limit": limit,
            "sort": "desc",
            "format": "json",
        })
    except Exception as e:
        logger.warning(f"[series] error fetching {ids_str[:60]}: {e}")
        return {}

    result = {}
    series_meta = data.get("meta", [])
    rows = data.get("data", [])

    if not rows:
        return result

    # La respuesta tiene columnas: [fecha, val_serie1, val_serie2, ...]
    # meta[0] es la fecha, meta[1..] son las series en el orden pedido
    for i, meta in enumerate(series_meta[1:], start=1):  # skip fecha
        sid = meta.get("field", {}).get("id", f"col_{i}")
        vals = []
        for row in rows:
            v = row[i] if len(row) > i else None
            vals.append(v)
        result[sid] = vals  # [más_reciente, anterior]

    return result


def _pct_change(v_new, v_old):
    """Variación porcentual entre dos valores."""
    if v_new is None or v_old is None or v_old == 0:
        return None
    return round((v_new - v_old) / abs(v_old) * 100, 2)

def _last(vals):
    """Primer valor no-None de una lista."""
    for v in (vals or []):
        if v is not None:
            return v
    return None


# ─── BCRA API — Variables adicionales ────────────────────────────────────────
BASE_BCRA = "https://api.bcra.gob.ar/estadisticas/v2.0/datosvariable"

BCRA_VARS = {
    # Variables que no están en el frontend actual
    "tasa_pf_30":   31,   # Tasa depósitos PF 30-44 días bancos privados
    "badlar_pub":   9,    # BADLAR bancos públicos
    "tasa_pase_1d": 5,    # Tasa pases pasivos 1 día (referencia corto)
    "m2_privado":   15,   # M2 privado (billetes + depósitos)
    "base_mon":     16,   # Base monetaria
    "tipo_cambio":  4,    # Tipo de cambio referencia BNA
}

def _fetch_bcra_var(var_id: int):
    try:
        url = f"{BASE_BCRA}/{var_id}/1/1"
        data = _get(url)
        v = data.get("results", [{}])[0].get("valor")
        return v
    except Exception as e:
        logger.warning(f"[bcra] var {var_id}: {e}")
        return None


# ─── FUNCIÓN PRINCIPAL ────────────────────────────────────────────────────────

def _build_indicadores_ext():
    """Construye el objeto completo. Se cachea 24hs."""

    resultado = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "mora": {},
        "senales": {},
        "actividad": {},
        "tasas_ext": {},
        "fuentes": {
            "mora": "datos.gob.ar / BCRA (serie 332.2)",
            "senales": "datos.gob.ar / INDEC (IPI cemento, EMI)",
            "actividad": "datos.gob.ar / INDEC (EMAE)",
            "tasas_ext": "BCRA API v2 + datos.gob.ar",
        }
    }

    # ── 1. Series de datos.gob.ar ────────────────────────────────────────────
    ids_a_pedir = list(SERIES.values())
    # Pedimos en dos lotes para no superar el límite de la API (~10 series por call)
    lote1 = ids_a_pedir[:6]
    lote2 = ids_a_pedir[6:]

    raw1 = _fetch_series(lote1, limit=3)
    raw2 = _fetch_series(lote2, limit=3)
    raw = {**raw1, **raw2}

    # Helper: obtener última valor de una serie por nombre lógico
    def sv(nombre):
        sid = SERIES.get(nombre)
        return _last(raw.get(sid, []))

    def sv_prev(nombre):
        vals = raw.get(SERIES.get(nombre), [])
        return vals[1] if len(vals) > 1 else None

    # ── 2. MORA ─────────────────────────────────────────────────────────────
    irreg_sis   = sv("irreg_sistema")
    irreg_priv  = sv("irreg_privados")
    cart_sis    = sv("cartera_sistema")
    cart_priv   = sv("cartera_priv")

    # Ratio de mora = cartera irregular / cartera total * 100
    mora_sistema  = round(irreg_sis  / cart_sis  * 100, 2) if irreg_sis  and cart_sis  else None
    mora_privados = round(irreg_priv / cart_priv * 100, 2) if irreg_priv and cart_priv else None

    # Variación mensual de montos (proxy de tendencia)
    irreg_sis_prev  = sv_prev("irreg_sistema")
    irreg_priv_prev = sv_prev("irreg_privados")

    resultado["mora"] = {
        "sistema_pct":   mora_sistema,     # % mora total sistema
        "privados_pct":  mora_privados,    # % mora bancos privados
        "irreg_sis_mm":  _pct_change(irreg_sis,  irreg_sis_prev),   # var mensual monto
        "irreg_priv_mm": _pct_change(irreg_priv, irreg_priv_prev),
        "nota": "Ratio calculado: cartera irregular / cartera total (BCRA vía datos.gob.ar)"
    }

    # ── 3. SEÑALES ADELANTADAS ───────────────────────────────────────────────
    cemento_act  = sv("cemento_ipi")
    cemento_prev = sv_prev("cemento_ipi")
    emi_act      = sv("emi_general")
    emi_prev     = sv_prev("emi_general")

    resultado["senales"] = {
        "cemento_ipi":    cemento_act,
        "cemento_var_mm": _pct_change(cemento_act, cemento_prev),
        "emi_idx":        emi_act,
        "emi_var_mm":     _pct_change(emi_act, emi_prev),
    }

    # ── 4. ACTIVIDAD (EMAE) ──────────────────────────────────────────────────
    emae_act  = sv("emae_general")
    emae_prev = sv_prev("emae_general")

    resultado["actividad"] = {
        "emae_idx":    emae_act,
        "emae_var_mm": _pct_change(emae_act, emae_prev),
        "emae_var_ya": None,  # se puede calcular si traemos 13 meses
    }

    # ── 5. TASAS EXTRA (BCRA) ────────────────────────────────────────────────
    # Llamadas BCRA solo para vars que no están en el frontend actual
    # (tasa política, BADLAR, reservas ya los maneja el frontend directamente)
    tasa_pf   = _fetch_bcra_var(BCRA_VARS["tasa_pf_30"])
    badlar_pub = _fetch_bcra_var(BCRA_VARS["badlar_pub"])
    tc_ref    = _fetch_bcra_var(BCRA_VARS["tipo_cambio"])

    resultado["tasas_ext"] = {
        "pf_30d_tna":    tasa_pf,                                       # TNA plazo fijo 30d
        "pf_30d_tea":    round(((1 + tasa_pf/100/365)**365 - 1)*100, 2) if tasa_pf else None,
        "badlar_pub":    badlar_pub,                                     # BADLAR bancos públicos
        "tc_ref_bna":    tc_ref,                                         # TC referencia BNA
    }

    return resultado


def get_indicadores_ext():
    """Entry point público — devuelve datos cacheados 24hs."""
    return _cached("indicadores_ext", _build_indicadores_ext) or {
        "error": "No se pudieron obtener datos externos",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


# ─── STANDALONE TEST ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(get_indicadores_ext(), indent=2, ensure_ascii=False))
