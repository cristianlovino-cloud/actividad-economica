"""
datos_externos.py — Datos reales para ECO RADAR (v2, oct-2026)

Fuentes (IDs verificados 22-oct-2026):
  • BCRA API v4.0  → https://api.bcra.gob.ar/estadisticas/v4.0/monetarias
      (la v2.0 fue dada de baja; un solo GET trae el último valor de todas las variables)
  • datos.gob.ar   → https://apis.datos.gob.ar/series/api/series/
      (cada serie se pide POR SEPARADO: si un ID falla, no tumba al resto)

Expone:
  get_indicadores_ext()  → mora, señales, EMAE, tasas extra
  get_bcra_core()        → inflación, BADLAR, TM20, PF, reservas, TC (para /api/indicadores)
"""

import time
import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "EcoRadar/2.0 (+https://github.com)"}
TIMEOUT = 15

# ─── CACHÉ ───────────────────────────────────────────────────────────────────
_cache = {}
TTL_OK = 60 * 60 * 6      # 6 h si vino bien
TTL_FAIL = 60 * 5         # 5 min si vino vacío (reintenta pronto)


def _cached(key, fn, ok_check):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[1] < hit[2]:
        return hit[0]
    try:
        data = fn()
    except Exception as e:
        logger.warning(f"[datos_ext] {key}: {e}")
        data = None
    ok = data is not None and ok_check(data)
    if ok:
        _cache[key] = (data, now, TTL_OK)
        return data
    # Falló: si hay un dato viejo bueno, devolverlo
    if hit and hit[2] == TTL_OK:
        return hit[0]
    _cache[key] = (data, now, TTL_FAIL)
    return data


def _get_json(url, params=None):
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    except requests.exceptions.SSLError:
        # api.bcra.gob.ar suele tener la cadena de certificados incompleta
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT, verify=False)
    r.raise_for_status()
    return r.json()


# ─── BCRA v4.0 ───────────────────────────────────────────────────────────────
BCRA_URL = "https://api.bcra.gob.ar/estadisticas/v4.0/monetarias"

BCRA_IDS = {
    "reservas":        1,    # Reservas internacionales (millones USD)
    "tc_minorista":    4,    # TC minorista promedio vendedor
    "tc_mayorista":    5,    # TC mayorista de referencia (Com. A 3500)
    "badlar_priv":     7,    # BADLAR bancos privados TNA
    "tm20_priv":       8,    # TM20 bancos privados TNA
    "pf_30d":          12,   # Tasa depósitos 30 días TNA
    "inflacion_mens":  27,   # Inflación mensual %
    "badlar_priv_tea": 35,   # BADLAR privados TEA
    "badlar_total":    138,  # BADLAR bancos públicos y privados TNA
    "tm20_total":      141,  # TM20 públicos y privados TNA
    "tasa_politica":   160,  # Tasa política monetaria TNA (BCRA dejó de fijarla en jul-2025)
}


def _fetch_bcra_all():
    """Un GET (paginado) a /monetarias → {idVariable: (valor, fecha)}."""
    out = {}
    offset = 0
    for _ in range(3):
        data = _get_json(BCRA_URL, params={"limit": 1000, "offset": offset})
        results = data.get("results", []) or []
        for it in results:
            vid = it.get("idVariable")
            if vid is not None:
                out[vid] = (it.get("ultValorInformado"), it.get("ultFechaInformada"))
        total = (data.get("metadata", {}).get("resultset", {}) or {}).get("count", 0)
        offset += len(results)
        if not results or offset >= total:
            break
    return out


def _bcra_all():
    return _cached("bcra_all", _fetch_bcra_all, lambda d: len(d) > 0) or {}


def _bv(name):
    v = _bcra_all().get(BCRA_IDS[name])
    return (v[0], v[1]) if v else (None, None)


def get_bcra_core():
    """Variables principales para /api/indicadores (claves que lee el frontend)."""
    infl, infl_f = _bv("inflacion_mens")
    badlar, badlar_f = _bv("badlar_priv")
    tm20, _ = _bv("tm20_priv")
    res, res_f = _bv("reservas")
    pol, pol_f = _bv("tasa_politica")
    return {
        "inflacion_mensual": infl,
        "inflacion_fecha":   infl_f,
        "badlar":            badlar,
        "badlar_fecha":      badlar_f,
        "tm20":              tm20,
        "reservas_bn":       round(res / 1000, 1) if res else None,  # miles de millones USD
        "reservas_fecha":    res_f,
        "tasa_politica":     pol,
        "tasa_politica_fecha": pol_f,
    }


# ─── DATOS.GOB.AR ────────────────────────────────────────────────────────────
SERIES_URL = "https://apis.datos.gob.ar/series/api/series/"

SERIES = {
    # Mora — ratio de irregularidad cartera privada, YA en % (aunque la API diga "millones")
    "mora_sistema":  "332.2_SISTEMA_FIADA__53",
    "mora_privados": "332.2_BANCOS_PRIADA__51",
    "mora_publicos": "332.2_BANCOS_PUBADA__55",
    "mora_nobanc":   "332.2_ENTIDADES_ADA__52",   # entidades financieras no bancarias
    "mora_priv_nac": "332.2_BANCOS_PRIADA__59",   # bancos privados nacionales
    # Señales
    "cemento":       "453.2_CEMENTONTO_0_0_7_59",       # IPI cemento, serie original
    "ipi_desest":    "453.1_SERIE_DESEADA_0_0_24_58",   # IPI manufacturero desestacionalizado (reemplaza EMI, discontinuado)
    # Actividad
    "emae_desest":   "143.3_NO_PR_2004_A_31",           # EMAE desestacionalizado
    "emae_orig":     "143.3_NO_PR_2004_A_21",           # EMAE original (para var. interanual)
    # Empleo privado registrado por provincia (miles) — original y desestacionalizado
    "emp_SF":   "154.1_SA_FE_FE_C_0_0_8",    "emp_SF_d": "154.2_SA_FE_FE_S_0_0_8",
    "emp_ER":   "154.1_EE_RIOSIOS_C_0_0_10",
    "emp_SJ":   "154.1_SJUANUAN_C_0_0_8",
    "emp_SC":   "154.1_SA_CRUZRUZ_C_0_0_10", "emp_SC_d": "154.2_SA_CRUZRUZ_S_0_0_10",
    # Tasa PF mensual (respaldo si falla BCRA)
    "pf_30_59":      "89.1_TIPF35D_0_0_35",
}


def _fetch_serie(sid, limit=14):
    """Devuelve lista [(fecha, valor), ...] desc, sin nulls."""
    data = _get_json(SERIES_URL, params={"ids": sid, "limit": limit, "sort": "desc", "format": "json"})
    rows = data.get("data", []) or []
    return [(r[0], r[1]) for r in rows if len(r) > 1 and r[1] is not None]


def _serie(name):
    sid = SERIES[name]
    return _cached(f"serie:{sid}", lambda: _fetch_serie(sid), lambda d: len(d) > 0) or []


def _pct(a, b):
    if a is None or b in (None, 0):
        return None
    return round((a - b) / abs(b) * 100, 2)


def _yoy(rows):
    """Var. interanual: último dato vs mismo mes del año anterior."""
    if not rows:
        return None
    f0, v0 = rows[0]
    target = f"{int(f0[:4]) - 1}{f0[4:]}"
    for f, v in rows:
        if f == target:
            return _pct(v0, v)
    return None


def _mom(rows):
    return _pct(rows[0][1], rows[1][1]) if len(rows) > 1 else None


def _seg(rows):
    """Resumen de una serie de mora (%): último, var m/m y 12m en pp, valor hace 1 año."""
    if not rows:
        return None
    hace12 = rows[12][1] if len(rows) > 12 else None
    return {
        "pct":     round(rows[0][1], 2),
        "var_pp":  round(rows[0][1] - rows[1][1], 2) if len(rows) > 1 else None,
        "var12_pp": round(rows[0][1] - hace12, 2) if hace12 is not None else None,
        "hace12":  round(hace12, 2) if hace12 is not None else None,
        "periodo": rows[0][0],
    }


def _prov_empleo(cod):
    orig = _serie(f"emp_{cod}")
    if not orig:
        return None
    des = _serie(f"emp_{cod}_d") if f"emp_{cod}_d" in SERIES else []
    base_mm = des if len(des) > 1 else orig
    return {
        "miles":   round(orig[0][1], 1),
        "var_ya":  _yoy(orig),
        "var_mm":  _mom(base_mm),
        "mm_desest": len(des) > 1,
        "periodo": orig[0][0],
    }


def _r(v, n=2):
    return round(v, n) if v is not None else None


# ─── ENDPOINT PRINCIPAL ──────────────────────────────────────────────────────
def _build():
    mora_s = _serie("mora_sistema")
    mora_p = _serie("mora_privados")
    cem = _serie("cemento")
    ipi = _serie("ipi_desest")
    emae_d = _serie("emae_desest")
    emae_o = _serie("emae_orig")
    pf_m = _serie("pf_30_59")

    pf, pf_f = _bv("pf_30d")
    if pf is None and pf_m:
        pf, pf_f = pf_m[0][1], pf_m[0][0]
    badlar_tot, _ = _bv("badlar_total")
    tc_may, tc_f = _bv("tc_mayorista")

    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "mora": {
            "sistema_pct":    _r(mora_s[0][1]) if mora_s else None,
            "privados_pct":   _r(mora_p[0][1]) if mora_p else None,
            "sistema_var_pp": _r(mora_s[0][1] - mora_s[1][1]) if len(mora_s) > 1 else None,
            "sistema_12m_pp": _r(mora_s[0][1] - mora_s[12][1]) if len(mora_s) > 12 else None,
            "periodo":        mora_s[0][0] if mora_s else None,
            "segmentos": {
                "privados":     _seg(mora_p),
                "publicos":     _seg(_serie("mora_publicos")),
                "no_bancarias": _seg(_serie("mora_nobanc")),
                "priv_nac":     _seg(_serie("mora_priv_nac")),
            },
        },
        "senales": {
            "cemento_ipi":    _r(cem[0][1], 1) if cem else None,
            "cemento_var_ya": _yoy(cem),
            "cemento_periodo": cem[0][0] if cem else None,
            "ipi_idx":        _r(ipi[0][1], 1) if ipi else None,
            "ipi_var_mm":     _mom(ipi),
            "ipi_periodo":    ipi[0][0] if ipi else None,
        },
        "actividad": {
            "emae_idx":    _r(emae_d[0][1], 1) if emae_d else None,
            "emae_var_mm": _mom(emae_d),
            "emae_var_ya": _yoy(emae_o),
            "periodo":     emae_d[0][0] if emae_d else None,
        },
        "provincias": {c: _prov_empleo(c) for c in ("SF", "ER", "SJ", "SC")},
        "tasas_ext": {
            "pf_30d_tna":   pf,
            "pf_30d_tea":   _r(((1 + pf / 100 / 365) ** 365 - 1) * 100) if pf else None,
            "pf_fecha":     pf_f,
            "badlar_total": badlar_tot,
            "tc_mayorista": tc_may,
            "tc_fecha":     tc_f,
        },
        "fuentes": {
            "mora": "BCRA vía datos.gob.ar (332.2 irregularidad cartera privada)",
            "senales": "INDEC vía datos.gob.ar (IPI cemento, IPI manufacturero)",
            "actividad": "INDEC vía datos.gob.ar (EMAE base 2004)",
            "tasas_ext": "BCRA API v4.0",
            "provincias": "SIPA vía datos.gob.ar (asalariados registrados sector privado)",
        },
    }


def _has_data(d):
    return any(v is not None for blk in ("mora", "senales", "actividad", "tasas_ext")
               for k, v in d.get(blk, {}).items() if k not in ("periodo",))


def get_indicadores_ext():
    data = _cached("indicadores_ext", _build, _has_data)
    return data or {"error": "No se pudieron obtener datos externos",
                    "timestamp": datetime.utcnow().isoformat() + "Z"}


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(get_bcra_core(), indent=2, ensure_ascii=False))
    print(json.dumps(get_indicadores_ext(), indent=2, ensure_ascii=False))
