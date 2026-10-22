/**
 * patch_frontend_ext.js
 * Funciones para consumir /api/indicadores-ext en ECO RADAR
 *
 * INTEGRACIÓN en el script principal (script_fixed.js / index.html):
 *
 *  1. Agregar llamada en refreshAll():
 *       const extResult = await safeGet(`${API_BASE}/api/indicadores-ext`);
 *       if (extResult) applyIndicadoresExt(extResult);
 *
 *  2. Agregar las funciones de abajo al script.
 *
 *  3. Los IDs de elementos HTML que se actualizan ya existen en el tablero,
 *     excepto los marcados con (*) que son nuevos y se agregan en el HTML.
 */

// ─── APLICAR DATOS EXTERNOS ───────────────────────────────────────────────────

function applyIndicadoresExt(ext) {
  if (!ext || ext.error) return;

  const { mora, senales, actividad, tasas_ext } = ext;

  // ── MORA ────────────────────────────────────────────────────────────────────
  if (mora) {
    applyMora(mora);
  }

  // ── SEÑALES ADELANTADAS (Tab Macro) ─────────────────────────────────────────
  if (senales) {
    applySenales(senales);
  }

  // ── ACTIVIDAD EMAE (Tab Actividad — indicador general) ──────────────────────
  if (actividad) {
    applyEmae(actividad);
  }

  // ── TASAS EXTRA (Tab Mora & Tasas) ──────────────────────────────────────────
  if (tasas_ext) {
    applyTasasExt(tasas_ext);
  }
}

// ─── MORA ─────────────────────────────────────────────────────────────────────

function applyMora(mora) {
  // Mora total sistema (el % grande en las cards)
  if (mora.sistema_pct != null) {
    // Card "Sistema" — valor principal
    const el = $('moraTotal');
    if (el) {
      el.textContent = `${mora.sistema_pct}%`;
      el.className = `mora-val ${mora.sistema_pct > 8 ? 'neg' : mora.sistema_pct > 5 ? 'neu' : 'pos'}`;
    }
    // Barra de progreso
    const bar = $('moraBarTotal');
    if (bar) bar.style.width = `${Math.min(mora.sistema_pct * 6, 100)}%`;
  }

  if (mora.privados_pct != null) {
    const el = $('moraPrivados');
    if (el) el.textContent = `${mora.privados_pct}%`;
  }

  // Variación mensual → subtítulo de la card
  if (mora.irreg_sis_mm != null) {
    const el = $('moraTotalTend');
    if (el) {
      const sign = mora.irreg_sis_mm > 0 ? '▲' : '▼';
      const cls  = mora.irreg_sis_mm > 0 ? 'neg' : 'pos'; // mora sube → malo
      el.innerHTML = `<span class="${cls}">${sign} ${Math.abs(mora.irreg_sis_mm).toFixed(1)}% vs mes ant.</span>`;
    }
  }
}

// ─── SEÑALES ADELANTADAS ──────────────────────────────────────────────────────

function applySenales(s) {
  // Cemento — IPI mensual
  if (s.cemento_var_mm != null) {
    const el = $('senalCemento');
    if (el) {
      const cls = s.cemento_var_mm > 0 ? 'pos' : s.cemento_var_mm < -2 ? 'neg' : 'neu';
      el.textContent = `${s.cemento_var_mm > 0 ? '+' : ''}${s.cemento_var_mm.toFixed(1)}%`;
      el.className = `card-val ${cls}`;
    }
    // Sub-label con índice
    const sub = $('senalCementoSub');
    if (sub && s.cemento_ipi) sub.textContent = `IPI: ${s.cemento_ipi.toFixed(1)} · var. mensual`;
  }

  // EMI — Estimador Mensual Industrial
  if (s.emi_var_mm != null) {
    const el = $('senalEMI');
    if (el) {
      const cls = s.emi_var_mm > 0 ? 'pos' : s.emi_var_mm < -1 ? 'neg' : 'neu';
      el.textContent = `${s.emi_var_mm > 0 ? '+' : ''}${s.emi_var_mm.toFixed(1)}%`;
      el.className = `card-val ${cls}`;
    }
    const sub = $('senalEMISub');
    if (sub && s.emi_idx) sub.textContent = `Idx: ${s.emi_idx.toFixed(1)} · INDEC`;
  }
}

// ─── EMAE ─────────────────────────────────────────────────────────────────────

function applyEmae(act) {
  if (act.emae_var_mm != null) {
    // Actualiza el indicador general de actividad en el sidebar de cada provincia
    // (como referencia nacional, no reemplaza los datos provinciales)
    const el = $('emaeNacional');
    if (el) {
      const cls = act.emae_var_mm > 0 ? 'pos' : act.emae_var_mm < -1 ? 'neg' : 'neu';
      el.innerHTML = `EMAE <span class="${cls}">${act.emae_var_mm > 0 ? '+' : ''}${act.emae_var_mm.toFixed(1)}%</span>`;
    }
  }
}

// ─── TASAS EXTRA ──────────────────────────────────────────────────────────────

function applyTasasExt(t) {
  // Plazo Fijo 30d TNA — ya existe el elemento en Tab Mora & Tasas
  if (t.pf_30d_tna != null) {
    const el = $('tPF');
    if (el) el.textContent = `${t.pf_30d_tna.toFixed(1)}%`;
    const tea = $('tPFTEA');
    if (tea && t.pf_30d_tea) tea.textContent = `TEA: ${t.pf_30d_tea.toFixed(1)}%`;
  }

  // BADLAR bancos públicos (complementa el privado que ya viene de BCRA)
  if (t.badlar_pub != null) {
    const el = $('tBadlarPub');
    if (el) el.textContent = `${t.badlar_pub.toFixed(1)}%`;
  }

  // TC referencia BNA
  if (t.tc_ref_bna != null) {
    const el = $('mTcRefBna');
    if (el) el.textContent = `$${fmt(t.tc_ref_bna)}`;
  }
}
