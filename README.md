# 🏦 ECO RADAR · Dashboard Actividad Económica
### Grupo Petersen | Banca Mayorista

Monitor en tiempo real de actividad económica sectorial para Santa Fe, Entre Ríos, San Juan y Santa Cruz. Clasificación SEPyME con alertas tempranas y noticias analizadas por Claude AI.

---

## 🗂 Estructura del repo

```
actividad-economica/
├── docs/
│   └── index.html          ← Frontend (GitHub Pages)
├── backend/
│   ├── app.py              ← API Flask (Render)
│   └── requirements.txt
└── README.md
```

---

## 🚀 Deploy en 3 pasos

### 1. Crear repo en GitHub

```bash
# En tu máquina local
git clone https://github.com/cristianlovino-cloud/actividad-economica
cd actividad-economica

# Copiá los archivos de este repo y luego:
git add .
git commit -m "init: eco radar dashboard"
git push origin main
```

### 2. GitHub Pages (frontend)

1. En el repo → **Settings → Pages**
2. Source: `Deploy from a branch`
3. Branch: `main` / Folder: `/docs`
4. URL resultado: `https://cristianlovino-cloud.github.io/actividad-economica`

### 3. Render (backend)

1. Ir a [render.com](https://render.com) → **New Web Service**
2. Conectar el repo de GitHub
3. Configurar:
   - **Root Directory:** `backend`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Plan:** Free tier OK para comenzar

4. **Variables de entorno** en Render:
   ```
   ANTHROPIC_API_KEY = sk-ant-...   ← tu clave de Anthropic
   ```

5. Copiar la URL del servicio (ej: `https://eco-radar-backend.onrender.com`)

6. Actualizar en `docs/index.html` línea:
   ```js
   const API_BASE = "https://eco-radar-backend.onrender.com"; // ← tu URL
   ```

---

## 🔌 Endpoints del backend

| Endpoint | TTL | Descripción |
|----------|-----|-------------|
| `GET /health` | — | Health check |
| `GET /api/indicadores` | 15 min | Dólar MEP/CCL/Blue + BCRA (inflación, tasas, reservas) |
| `GET /api/noticias` | 1 hora | RSS feeds clasificados por Claude (sector, sentimiento, alerta) |
| `GET /api/sectores/{SF\|ER\|SJ\|SC}` | 30 min | Sectores SEPyME por provincia |

---

## ⚙️ Fuentes de datos

| Fuente | Datos |
|--------|-------|
| [dolarapi.com](https://dolarapi.com) | Dólar MEP, CCL, Blue, Oficial |
| [BCRA API](https://api.bcra.gob.ar) | Inflación, tasas, reservas, base monetaria |
| RSS Cronista / Infobae / Ámbito / Agrofy | Noticias económicas |
| Google News RSS | Minería, Oil&Gas, PyME |
| **Claude Haiku** | Clasificación de noticias por sector + alerta temprana |

---

## 🧠 Lógica de clasificación

Cada noticia pasa por Claude Haiku y retorna:
- **sector**: agricultura | mineria | oil_gas | energia | construccion | comercio | tecnologia | turismo | pesca | vitivinicultura | general
- **sentimiento**: positivo | negativo | neutro
- **provincias**: [SF, ER, SJ, SC] afectadas
- **alerta_temprana**: true si implica riesgo o caída para el sector
- **resumen_corto**: síntesis accionable ≤ 80 chars

Si `ANTHROPIC_API_KEY` no está seteada, cae a clasificación por keywords (fallback local).

---

## 🎯 Lógica de oportunidades comerciales

| Badge | Criterio |
|-------|----------|
| ▲ CRECER | varA > 4% y tendencia sostenida |
| ◆ DEFENDER | varA 1-4%, sector estable |
| ○ OBSERVAR | varA -1% a +1%, sin tendencia |
| ▼ SALIR | varA < -1% o caída acelerada |

---

## 🔄 Próximas iteraciones sugeridas

- [ ] Integrar INDEC – Estimador Mensual de Actividad Económica (EMAE) por provincia
- [ ] Conectar IERAL para datos sectoriales desagregados
- [ ] Alertas por email/Slack cuando alerta_temprana = true
- [ ] Serie histórica real desde BCRA para las sparklines
- [ ] Login simple con password para proteger acceso interno

---

## 📦 Dependencias backend

```
flask==3.1.0
flask-cors==5.0.0
requests==2.32.3
feedparser==6.0.11
anthropic==0.50.0
gunicorn==23.0.0
```

---

*Grupo Petersen · Banca Mayorista · Planeamiento Estratégico*
