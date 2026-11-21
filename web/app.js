/* StatCraft Web — app shell: worksheet, analysis forms, results, engine bridge. Spanish UI. */
(() => {
  'use strict';
  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = Charts.esc;
  const fmt = Charts.fmt;

  // ------------------------------------------------------------------ state
  const MIN_ROWS = 15;
  const state = {
    columns: [],   // {name, kind:'number'|'text', cells:[string]}
    results: [],   // {id, analysis, title, subtitle, result}
    nextId: 1,
  };

  function store(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode */ } }
  function load(key) { try { return JSON.parse(localStorage.getItem(key)); } catch (e) { return null; } }
  const saveData = () => store('sc.data.v1', state.columns);

  function newColumn(index) { return { name: 'C' + (index + 1), kind: 'number', cells: [] }; }
  function rowCount() { return Math.max(MIN_ROWS, ...state.columns.map((c) => c.cells.length)); }

  // ------------------------------------------------------------------ numbers & paste parsing
  const NUM_RE = /^[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?$/;
  function parseNumber(text) {
    const t = String(text ?? '').trim().replace(/\s/g, '');
    if (t === '') return null;
    if (!NUM_RE.test(t)) return NaN;
    return Number(t.replace(',', '.'));
  }

  function splitDelimited(text, delim) {
    const rows = [];
    let row = [], cell = '', quoted = false;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (quoted) {
        if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; }
        else if (ch === '"') quoted = false;
        else cell += ch;
      } else if (ch === '"' && cell === '') quoted = true;
      else if (ch === delim) { row.push(cell); cell = ''; }
      else if (ch === '\n' || ch === '\r') {
        if (ch === '\r' && text[i + 1] === '\n') i++;
        row.push(cell); rows.push(row); row = []; cell = '';
      } else cell += ch;
    }
    if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
    return rows.filter((r) => r.some((c) => c.trim() !== ''));
  }

  function parseTable(text, headerMode) {
    const delim = text.includes('\t') ? '\t' : (text.match(/;/g) || []).length ? ';' : ',';
    const rows = splitDelimited(text.replace(/^﻿/, ''), delim);
    if (!rows.length) return [];
    const width = Math.max(...rows.map((r) => r.length));
    rows.forEach((r) => { while (r.length < width) r.push(''); });
    const isNum = (s) => s.trim() !== '' && !Number.isNaN(parseNumber(s));
    let hasHeader;
    if (headerMode === 'yes') hasHeader = true;
    else if (headerMode === 'no') hasHeader = false;
    else {
      hasHeader = rows.length > 1 && rows[0].some((c) => c.trim() !== '' && !isNum(c)) &&
        rows[1].some((c, j) => isNum(c) && !isNum(rows[0][j])) || (rows.length > 1 && rows[0].every((c) => c.trim() !== '' && !isNum(c)) && rows.slice(1).some((r) => r.some(isNum)));
    }
    const head = hasHeader ? rows[0] : null;
    const body = hasHeader ? rows.slice(1) : rows;
    const cols = [];
    for (let j = 0; j < width; j++) {
      const cells = body.map((r) => r[j].trim());
      const filled = cells.filter((c) => c !== '');
      const numeric = filled.length > 0 && filled.filter(isNum).length / filled.length >= 0.9;
      cols.push({ name: (head && head[j].trim()) || 'C' + (j + 1), kind: numeric ? 'number' : 'text', cells });
    }
    return cols;
  }

  // ------------------------------------------------------------------ worksheet grid
  function renderGrid() {
    const n = rowCount();
    let h = '<table class="grid"><thead><tr><th class="rown">#</th>';
    state.columns.forEach((c, j) => {
      h += `<th><button class="colhead" data-col="${j}" aria-label="Columna ${esc(c.name)}, ${c.kind === 'number' ? 'numérica' : 'texto'}. Tocar para editar">${esc(c.name)}<small>${c.kind === 'number' ? 'numérica' : 'texto'}</small></button></th>`;
    });
    h += '</tr></thead><tbody>';
    for (let i = 0; i < n; i++) {
      h += `<tr><td class="rown">${i + 1}</td>`;
      state.columns.forEach((c, j) => {
        const v = c.cells[i] ?? '';
        const bad = c.kind === 'number' && v !== '' && Number.isNaN(parseNumber(v));
        h += `<td class="${c.kind === 'number' ? 'num' : ''}"><input type="text" inputmode="text" enterkeyhint="next" autocomplete="off" autocapitalize="off" spellcheck="false" data-r="${i}" data-c="${j}" value="${esc(v)}" class="${bad ? 'bad' : ''}" aria-label="Fila ${i + 1}, ${esc(c.name)}"></td>`;
      });
      h += '</tr>';
    }
    $('#grid-wrap').innerHTML = h + '</tbody></table>';
    updateHint();
  }

  function updateHint() {
    const rows = Math.max(0, ...state.columns.map((c) => lastFilled(c) + 1));
    const hint = $('#data-hint');
    hint.textContent = state.columns.length && rows
      ? `${rows} filas × ${state.columns.length} columnas. Toca un encabezado para renombrar o cambiar el tipo.`
      : 'Hoja vacía. Usa “Pegar datos” (desde Excel o un CSV) o carga un ejemplo.';
  }
  function lastFilled(c) { for (let i = c.cells.length - 1; i >= 0; i--) if (c.cells[i] !== '') return i; return -1; }

  function setData(cols) {
    state.columns = cols.length ? cols : [newColumn(0), newColumn(1)];
    saveData(); renderGrid();
  }

  $('#grid-wrap').addEventListener('input', (e) => {
    const t = e.target;
    if (!t.matches('input[data-r]')) return;
    const c = state.columns[+t.dataset.c];
    const r = +t.dataset.r;
    while (c.cells.length <= r) c.cells.push('');
    c.cells[r] = t.value;
    t.classList.toggle('bad', c.kind === 'number' && t.value.trim() !== '' && Number.isNaN(parseNumber(t.value)));
    saveData(); updateHint();
  });
  $('#grid-wrap').addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || !e.target.matches('input[data-r]')) return;
    e.preventDefault();
    const next = $(`input[data-r="${+e.target.dataset.r + 1}"][data-c="${e.target.dataset.c}"]`);
    if (next) next.focus();
  });
  $('#grid-wrap').addEventListener('click', (e) => {
    const b = e.target.closest('.colhead');
    if (b) openColumnSheet(+b.dataset.col);
  });

  // ------------------------------------------------------------------ sheets (bottom dialogs) & toast
  let sheetReturnFocus = null;
  function openSheet({ title, body, buttons = [], onOpen }) {
    sheetReturnFocus = document.activeElement;
    $('#sheet-title').textContent = title;
    $('#sheet-body').innerHTML = body;
    const foot = $('#sheet-foot');
    foot.innerHTML = '';
    buttons.forEach((b) => {
      const el = document.createElement('button');
      el.className = 'btn ' + (b.cls || '');
      el.textContent = b.label;
      el.addEventListener('click', () => b.onClick());
      foot.appendChild(el);
    });
    foot.hidden = !buttons.length;
    $('#sheet').hidden = false;
    $('#sheet-backdrop').hidden = false;
    document.body.style.overflow = 'hidden';
    if (onOpen) onOpen();
    const first = $('#sheet-body input, #sheet-body select, #sheet-body textarea, #sheet-body button');
    if (first && !matchMedia('(pointer: coarse)').matches) first.focus();
  }
  function closeSheet() {
    $('#sheet').hidden = true;
    $('#sheet-backdrop').hidden = true;
    document.body.style.overflow = '';
    if (sheetReturnFocus && sheetReturnFocus.focus) sheetReturnFocus.focus();
  }
  $('#sheet-close').addEventListener('click', closeSheet);
  $('#sheet-backdrop').addEventListener('click', closeSheet);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#sheet').hidden) closeSheet(); });

  let toastTimer = null;
  function toast(msg, kind = 'error') {
    const el = $('#toast');
    el.textContent = msg;
    el.className = 'toast' + (kind === 'info' ? ' info' : '');
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, kind === 'info' ? 2600 : 7000);
  }

  // ------------------------------------------------------------------ data actions
  function openColumnSheet(j) {
    const c = state.columns[j];
    openSheet({
      title: 'Columna ' + (j + 1),
      body: `<label class="field"><span>Nombre</span><input type="text" id="col-name" value="${esc(c.name)}" maxlength="40"></label>
             <label class="field"><span>Tipo de datos</span><select id="col-kind"><option value="number">Numérica</option><option value="text">Texto (categorías)</option></select></label>`,
      onOpen: () => { $('#col-kind').value = c.kind; },
      buttons: [
        { label: 'Eliminar', cls: 'danger', onClick: () => { state.columns.splice(j, 1); if (!state.columns.length) state.columns.push(newColumn(0)); saveData(); renderGrid(); closeSheet(); } },
        { label: 'Guardar', cls: 'primary', onClick: () => { c.name = $('#col-name').value.trim() || 'C' + (j + 1); c.kind = $('#col-kind').value; saveData(); renderGrid(); closeSheet(); } },
      ],
    });
  }

  function openPasteSheet() {
    openSheet({
      title: 'Pegar o importar datos',
      body: `<p class="note">Copia celdas en Excel o Google Sheets y pégalas aquí, o elige un archivo CSV.</p>
        <label class="field"><span>Datos</span><textarea id="paste-text" placeholder="Pega aquí…" spellcheck="false"></textarea></label>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn" id="paste-clip">Pegar del portapapeles</button>
          <label class="btn" style="display:inline-flex;align-items:center">Elegir archivo CSV<input id="paste-file" type="file" accept=".csv,.tsv,.txt,text/csv,text/plain" hidden></label>
        </div>
        <label class="field"><span>Primera fila</span><select id="paste-header"><option value="auto">Detectar encabezados automáticamente</option><option value="yes">Son encabezados</option><option value="no">Son datos</option></select></label>`,
      onOpen: () => {
        $('#paste-clip').addEventListener('click', async () => {
          try { $('#paste-text').value = await navigator.clipboard.readText(); }
          catch (e) { toast('No se pudo leer el portapapeles. Mantén presionado en el cuadro y elige “Pegar”.'); }
        });
        $('#paste-file').addEventListener('change', async (e) => { const f = e.target.files[0]; if (f) $('#paste-text').value = await f.text(); });
      },
      buttons: [
        { label: 'Cancelar', onClick: closeSheet },
        { label: 'Importar', cls: 'primary', onClick: () => {
          const text = $('#paste-text').value;
          if (!text.trim()) { toast('No hay datos para importar.'); return; }
          const cols = parseTable(text, $('#paste-header').value);
          if (!cols.length) { toast('No se reconocieron datos en el texto.'); return; }
          setData(cols); closeSheet(); toast(`Se importaron ${cols.length} columnas y ${Math.max(...cols.map((c) => c.cells.length))} filas.`, 'info');
        } },
      ],
    });
  }

  function openSamplesSheet() {
    openSheet({
      title: 'Datos de ejemplo',
      body: '<ul class="list">' + SAMPLES.map((s) => `<li><button data-sample="${s.id}">${esc(s.title)}<small>${esc(s.hint)}</small></button></li>`).join('') + '</ul>',
      onOpen: () => {
        $('#sheet-body').addEventListener('click', (e) => {
          const b = e.target.closest('[data-sample]');
          if (!b) return;
          const s = SAMPLES.find((x) => x.id === b.dataset.sample);
          setData(s.columns.map((c) => ({ name: c.name, kind: c.kind, cells: c.values.map((v) => String(v)) })));
          closeSheet(); toast('Ejemplo cargado: ' + s.title, 'info');
        });
      },
    });
  }

  $('#btn-paste').addEventListener('click', openPasteSheet);
  $('#btn-samples').addEventListener('click', openSamplesSheet);
  $('#btn-addrow').addEventListener('click', () => {
    const n = rowCount() + 10;
    state.columns.forEach((c) => { while (c.cells.length < n) c.cells.push(''); });
    renderGrid();
    const wrap = $('#grid-wrap'); wrap.scrollTop = wrap.scrollHeight;
  });
  $('#btn-addcol').addEventListener('click', () => { state.columns.push(newColumn(state.columns.length)); saveData(); renderGrid(); const w = $('#grid-wrap'); w.scrollLeft = w.scrollWidth; });
  $('#btn-clear').addEventListener('click', () => {
    openSheet({
      title: '¿Limpiar la hoja?', body: '<p>Se borrarán todos los datos de la hoja. Los resultados ya calculados se conservan.</p>',
      buttons: [{ label: 'Cancelar', onClick: closeSheet }, { label: 'Borrar datos', cls: 'danger', onClick: () => { setData([]); closeSheet(); } }],
    });
  });

  // ------------------------------------------------------------------ engine bridge
  const engine = { worker: null, ready: false, pending: new Map(), seq: 0 };
  function setEngineChip(stateName, text) { const el = $('#engine'); el.dataset.state = stateName; el.textContent = text; }

  function startEngine() {
    const q = new URLSearchParams(location.search);
    const qs = [];
    if (q.get('pyodide')) qs.push('pyodide=' + encodeURIComponent(q.get('pyodide')));
    if (q.get('engine')) qs.push('engine=' + encodeURIComponent(q.get('engine')));
    engine.worker = new Worker('worker.js' + (qs.length ? '?' + qs.join('&') : ''));
    engine.worker.onmessage = (e) => {
      const m = e.data;
      if (m.type === 'status') setEngineChip('loading', m.text);
      else if (m.type === 'ready') { engine.ready = true; setEngineChip('ready', 'Motor listo'); document.body.dataset.engine = 'ready'; }
      else if (m.type === 'fatal') { setEngineChip('error', 'Error del motor'); document.body.dataset.engine = 'error'; engine.fatal = m.error; toast('No se pudo iniciar el motor de cálculo: ' + m.error); }
      else if (engine.pending.has(m.id)) { const p = engine.pending.get(m.id); engine.pending.delete(m.id); m.ok ? p.resolve(JSON.parse(m.json)) : p.reject(new Error(m.error)); }
    };
    engine.worker.onerror = (e) => { setEngineChip('error', 'Error del motor'); toast('Error del motor: ' + (e.message || 'desconocido')); };
  }
  function callEngine(analysis, options) {
    if (engine.fatal) return Promise.reject(new Error('El motor de cálculo no está disponible: ' + engine.fatal));
    const payload = { columns: state.columns.map(typedColumn), options };
    return new Promise((resolve, reject) => {
      const id = ++engine.seq;
      engine.pending.set(id, { resolve, reject });
      engine.worker.postMessage({ id, analysis, payload });
    });
  }
  function typedColumn(c) {
    if (c.kind === 'text') return { name: c.name, kind: 'text', values: c.cells.map((v) => (v.trim() === '' ? null : v.trim())) };
    const values = c.cells.map((v, i) => {
      const x = parseNumber(v);
      if (Number.isNaN(x)) throw new Error(`La columna “${c.name}” tiene un valor no numérico en la fila ${i + 1}: “${v}”. Corrígelo o cambia la columna a tipo texto.`);
      return x;
    });
    return { name: c.name, kind: 'number', values };
  }

  // ------------------------------------------------------------------ analysis catalog
  const ICONS = {
    describe: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    histogram: '<path d="M3 20V13h4v7M9 20V6h4v14M15 20v-9h4v9M2 20h20"/>',
    boxplot: '<path d="M7 7h10v9H7zM7 12h10M12 3v4M12 16v5"/>',
    scatter: '<circle cx="6" cy="17" r="1.5"/><circle cx="10" cy="12" r="1.5"/><circle cx="14" cy="14" r="1.5"/><circle cx="18" cy="7" r="1.5"/><path d="M3 21h18M3 3v18"/>',
    run_chart: '<path d="M3 16l4-5 4 3 5-8 5 6M3 12h18" />',
    imr: '<path d="M3 5h18M3 19h18M3 12h18" stroke-dasharray="3 2"/><path d="M4 13l4-3 3 5 4-8 5 4"/>',
    pareto: '<path d="M4 20V9h3v11M9 20v-7h3v7M14 20v-4h3v4M3 4c4 0 8 1 11 4s5 3 7 3"/>',
  };
  const ANALYSES = [
    { id: 'describe', title: 'Estadísticas descriptivas', desc: 'Media, desviación estándar, cuartiles, mínimo y máximo.',
      fields: [{ key: 'columns', type: 'cols', num: true, label: 'Variables (una o varias)' }] },
    { id: 'histogram', title: 'Histograma', desc: 'Distribución de una variable en barras.',
      fields: [{ key: 'column', type: 'col', num: true, label: 'Variable' }, { key: 'bins', type: 'int', def: 8, min: 2, max: 100, label: 'Número de barras' }, { key: 'fit_normal', type: 'check', label: 'Dibujar curva normal' }] },
    { id: 'boxplot', title: 'Diagrama de caja', desc: 'Mediana, cuartiles y valores atípicos; opcional por grupos.',
      fields: [{ key: 'columns', type: 'cols', num: true, label: 'Variables' }, { key: 'group', type: 'col', optional: true, label: 'Agrupar por (opcional)' }] },
    { id: 'scatter', title: 'Diagrama de dispersión', desc: 'Relación entre dos variables, con recta de regresión opcional.',
      fields: [{ key: 'x', type: 'col', num: true, label: 'Variable X', pick: 'first' }, { key: 'y', type: 'col', num: true, label: 'Variable Y', pick: 'second' },
        { key: 'mode', type: 'select', label: 'Tipo', def: 'regression', options: [['simple', 'Simple'], ['regression', 'Con recta de regresión'], ['groups', 'Con grupos'], ['regression_groups', 'Con regresión y grupos'], ['connect', 'Con línea de conexión']] },
        { key: 'group', type: 'col', optional: true, label: 'Grupos (para tipos con grupos)' }] },
    { id: 'run_chart', title: 'Gráfica de corridas', desc: 'Detecta agrupamiento, mezcla, tendencias y oscilaciones en el tiempo.',
      fields: [{ key: 'column', type: 'col', num: true, label: 'Variable' }, { key: 'subgroup_size', type: 'int', def: 1, min: 1, max: 50, label: 'Tamaño de subgrupo' }] },
    { id: 'imr', title: 'Gráfica de control I-MR', desc: 'Individuales y rango móvil con límites de control y pruebas de causas especiales.',
      fields: [{ key: 'column', type: 'col', num: true, label: 'Variable' },
        { key: 'estimation_method', type: 'select', label: 'Estimación de σ', def: 'amr', options: [['amr', 'Promedio de rangos móviles'], ['mmr', 'Mediana de rangos móviles']] },
        { key: 'k_sigma', type: 'number', def: 3, min: 1, max: 6, step: 0.5, label: 'Límites a ± K sigmas' },
        { key: 'test2', type: 'check', label: 'Prueba 2: 9 puntos seguidos del mismo lado de la línea central', def: true },
        { key: 'test3', type: 'check', label: 'Prueba 3: 6 puntos seguidos subiendo o bajando' },
        { key: 'test4', type: 'check', label: 'Prueba 4: 14 puntos alternando arriba y abajo' }],
      toOptions: (v) => ({ column: v.column, estimation_method: v.estimation_method, k_sigma: v.k_sigma,
        tests: { test1: { enabled: true, k: v.k_sigma }, test2: { enabled: v.test2, k: 9 }, test3: { enabled: v.test3, k: 6 }, test4: { enabled: v.test4, k: 14 } } }) },
    { id: 'pareto', title: 'Diagrama de Pareto', desc: 'Ordena las causas de mayor a menor y muestra el porcentaje acumulado.',
      fields: [{ key: 'defect', type: 'col', label: 'Categoría o defecto', pick: 'text' }, { key: 'count', type: 'col', num: true, optional: true, label: 'Frecuencia (vacío = contar filas)', pick: 'lastnum' },
        { key: 'combine_percent', type: 'number', def: 95, min: 50, max: 100, step: 1, label: 'Agrupar en “Otros” después de (% acumulado)' }] },
  ];

  function renderCatalog() {
    $('#analysis-list').innerHTML = ANALYSES.map((a) => `<button class="card-btn" data-analysis="${a.id}"><svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[a.id]}</svg><div><b>${a.title}</b><span>${a.desc}</span></div></button>`).join('');
  }
  $('#analysis-list').addEventListener('click', (e) => {
    const b = e.target.closest('[data-analysis]');
    if (b) openAnalysisSheet(ANALYSES.find((a) => a.id === b.dataset.analysis));
  });

  function defaultColumn(field) {
    const nums = state.columns.map((c, i) => (c.kind === 'number' ? i : -1)).filter((i) => i >= 0);
    const texts = state.columns.map((c, i) => (c.kind === 'text' ? i : -1)).filter((i) => i >= 0);
    if (field.optional && field.pick !== 'lastnum') return -1;
    if (field.pick === 'first') return nums[0] ?? 0;
    if (field.pick === 'second') return nums[1] ?? nums[0] ?? 0;
    if (field.pick === 'text') return texts[0] ?? 0;
    if (field.pick === 'lastnum') return nums.length ? nums[nums.length - 1] : -1;
    return nums.length ? nums[nums.length - 1] : 0;
  }

  function fieldHTML(f) {
    const colOptions = (numOnly, optional, selected) => (optional ? `<option value="-1" ${selected === -1 ? 'selected' : ''}>— ninguna —</option>` : '') +
      state.columns.map((c, i) => (numOnly && c.kind !== 'number' ? '' : `<option value="${i}" ${i === selected ? 'selected' : ''}>${esc(c.name)}${c.kind === 'text' ? ' (texto)' : ''}</option>`)).join('');
    if (f.type === 'col') return `<label class="field"><span>${f.label}</span><select data-key="${f.key}">${colOptions(f.num, f.optional, defaultColumn(f))}</select></label>`;
    if (f.type === 'cols') {
      const nums = state.columns.map((c, i) => (c.kind === 'number' ? i : -1)).filter((i) => i >= 0);
      const pre = f.key === 'columns' && nums.length > 1 ? nums.slice(-1) : nums;
      return `<label class="field"><span>${f.label}</span><select data-key="${f.key}" multiple size="${Math.min(6, Math.max(3, state.columns.length))}">${state.columns.map((c, i) => (f.num && c.kind !== 'number' ? '' : `<option value="${i}" ${pre.includes(i) ? 'selected' : ''}>${esc(c.name)}</option>`)).join('')}</select></label>`;
    }
    if (f.type === 'select') return `<label class="field"><span>${f.label}</span><select data-key="${f.key}">${f.options.map(([v, l]) => `<option value="${v}" ${v === f.def ? 'selected' : ''}>${l}</option>`).join('')}</select></label>`;
    if (f.type === 'check') return `<label class="check"><input type="checkbox" data-key="${f.key}" ${f.def ? 'checked' : ''}><span>${f.label}</span></label>`;
    return `<label class="field"><span>${f.label}</span><input type="number" inputmode="decimal" data-key="${f.key}" value="${f.def}" min="${f.min}" max="${f.max}" step="${f.step || 1}"></label>`;
  }
  function readField(f) {
    const el = $(`#sheet-body [data-key="${f.key}"]`);
    if (f.type === 'cols') return [...el.selectedOptions].map((o) => +o.value);
    if (f.type === 'col') return +el.value;
    if (f.type === 'check') return el.checked;
    if (f.type === 'select') return el.value;
    const v = Number(el.value);
    return Number.isFinite(v) ? v : f.def;
  }

  function openAnalysisSheet(a) {
    if (!state.columns.some((c) => lastFilled(c) >= 0)) { toast('Primero agrega datos en la pestaña Datos.'); switchView('data'); return; }
    openSheet({
      title: a.title,
      body: a.fields.map(fieldHTML).join(''),
      buttons: [{ label: 'Cancelar', onClick: closeSheet }, { label: 'Ejecutar', cls: 'primary', onClick: () => runAnalysis(a) }],
    });
  }

  async function runAnalysis(a) {
    const values = {};
    a.fields.forEach((f) => { values[f.key] = readField(f); });
    for (const f of a.fields) {
      if (f.type === 'cols' && !values[f.key].length) { toast('Selecciona al menos una variable.'); return; }
    }
    const options = a.toOptions ? a.toOptions(values) : values;
    if (options.group === -1) delete options.group;
    if (options.count === -1) delete options.count;
    const subtitle = a.fields.filter((f) => f.type === 'col' || f.type === 'cols').map((f) => [].concat(values[f.key]).filter((i) => i >= 0).map((i) => state.columns[i].name).join(', ')).filter(Boolean).join(' · ');
    const btn = $('#sheet-foot .primary');
    btn.disabled = true; btn.textContent = engine.ready ? 'Calculando…' : 'Esperando al motor…';
    try {
      const response = await callEngine(a.id, options);
      if (!response.ok) throw new Error(response.error.replace(/^\w+Error: /, ''));
      if (a.id === 'pareto') response.result.categories = response.result.categories.map((c) => (c === 'Other' ? 'Otros' : c));
      state.results.unshift({ id: state.nextId++, analysis: a.id, title: a.title, subtitle, result: response.result });
      closeSheet(); renderResults(); switchView('results');
    } catch (err) {
      btn.disabled = false; btn.textContent = 'Ejecutar';
      toast(err.message || String(err));
    }
  }

  // ------------------------------------------------------------------ results rendering
  const STAT_ROWS = [['count', 'N'], ['missing', 'Faltantes'], ['mean', 'Media'], ['standard_error', 'Error estándar'], ['sample_stdev', 'Desv. estándar'], ['sample_variance', 'Varianza'], ['minimum', 'Mínimo'], ['q1', 'Q1'], ['median', 'Mediana'], ['q3', 'Q3'], ['maximum', 'Máximo'], ['sum', 'Suma']];
  const table = (rows, head) => `<table class="kv">${head ? `<thead><tr>${head.map((h) => `<th>${h}</th>`).join('')}</tr></thead>` : ''}<tbody>${rows.map((r) => `<tr>${r.map((c, i) => (i === 0 && !head ? `<th scope="row">${c}</th>` : `<td>${c}</td>`)).join('')}</tr>`).join('')}</tbody></table>`;
  const pval = (p) => (p === null || p === undefined ? '—' : p < 0.001 ? '< 0.001' : p.toFixed(3));

  function pearson(x, y) {
    const pts = x.map((v, i) => [v, y[i]]).filter(([a, b]) => a !== null && b !== null);
    const n = pts.length; if (n < 3) return null;
    const mx = pts.reduce((s, p) => s + p[0], 0) / n, my = pts.reduce((s, p) => s + p[1], 0) / n;
    let sxy = 0, sxx = 0, syy = 0;
    pts.forEach(([a, b]) => { sxy += (a - mx) * (b - my); sxx += (a - mx) ** 2; syy += (b - my) ** 2; });
    return sxx && syy ? sxy / Math.sqrt(sxx * syy) : null;
  }

  function resultBody(r) {
    const res = r.result;
    switch (r.analysis) {
      case 'describe':
        return res.items.map((it) => `<h4 style="margin:12px 0 0">${esc(it.name)}</h4>` + table(STAT_ROWS.filter(([k]) => it.stats[k] !== undefined).map(([k, l]) => [l, k === 'count' || k === 'missing' ? it.stats[k] : fmt(it.stats[k], 5)]))).join('');
      case 'histogram': {
        const s = res.panels[0].series[0];
        return Charts.render(res, r.analysis) + table([['N', s.count], ['Media', fmt(s.mean, 5)], ['Desv. estándar', fmt(s.stdev, 5)], ['Barras', s.counts.length]]);
      }
      case 'boxplot':
        return Charts.render(res, r.analysis) + table(res.panels[0].items.map((it) => [esc(it.label), fmt(it.box.q1), fmt(it.box.median), fmt(it.box.q3), it.box.outliers.length]), ['Grupo', 'Q1', 'Mediana', 'Q3', 'Atípicos']);
      case 'scatter': {
        let extra = '';
        if (res.series.length === 1) { const rr = pearson(res.series[0].x, res.series[0].y); if (rr !== null) extra += `<tr><th scope="row">Correlación (r)</th><td>${fmt(rr, 4)}</td></tr>`; }
        (res.fits || []).forEach((f, i) => { extra += `<tr><th scope="row">Recta${res.fits.length > 1 ? ' ' + esc(f.group) : ''}</th><td>y = ${fmt(f.intercept)} ${f.slope < 0 ? '−' : '+'} ${fmt(Math.abs(f.slope))}·x</td></tr>`; });
        return Charts.render(res, r.analysis) + (extra ? `<table class="kv"><tbody>${extra}</tbody></table>` : '') + `<p class="note">${res.count} puntos${res.missing ? `, ${res.missing} omitidos por datos faltantes` : ''}.</p>`;
      }
      case 'run_chart': {
        const a = res.runs_about_median, b = res.runs_up_or_down;
        const flags = [];
        if (a.p_cluster < 0.05) flags.push('agrupamiento (valores parecidos seguidos)');
        if (a.p_mixture < 0.05) flags.push('mezcla de dos fuentes');
        if (b.p_trend < 0.05) flags.push('tendencia');
        if (b.p_oscillation < 0.05) flags.push('oscilación');
        return Charts.render(res, r.analysis) + table([
          ['Corridas respecto a la mediana', `${a.number_of_runs} (esperadas ${fmt(a.expected_runs, 3)})`], ['Corrida más larga', a.longest_run],
          ['Valor p · agrupamiento', pval(a.p_cluster)], ['Valor p · mezcla', pval(a.p_mixture)],
          ['Corridas arriba/abajo', `${b.number_of_runs} (esperadas ${fmt(b.expected_runs, 3)})`], ['Valor p · tendencia', pval(b.p_trend)], ['Valor p · oscilación', pval(b.p_oscillation)]])
          + `<p class="verdict ${flags.length ? 'warn' : 'good'}">${flags.length ? 'Posible patrón no aleatorio: ' + flags.join(', ') + ' (α = 0.05).' : 'No hay evidencia de patrones no aleatorios (α = 0.05).'}</p>`;
      }
      case 'imr': {
        const fails = Object.entries(res.test_failures || {});
        const list = fails.map(([i, t]) => `obs. ${i} (${t.map((x) => 'prueba ' + x).join(', ')})`);
        const mrBad = (res.mr_signals || []).map(Number);
        return Charts.render(res, r.analysis) + table([['Línea central (X̄)', fmt(res.i_center, 5)], ['LCS individuales', fmt(res.i_ucl, 5)], ['LCI individuales', fmt(res.i_lcl, 5)], ['Rango móvil medio', fmt(res.mr_center, 5)], ['LCS rango móvil', fmt(res.mr_ucl, 5)], ['σ estimada', fmt(res.within_stdev, 5)]])
          + `<p class="verdict ${list.length || mrBad.length ? 'warn' : 'good'}">${list.length ? 'Individuales fuera de control: ' + esc(list.join('; ')) + '.' : 'Individuales: ningún punto fuera de control con las pruebas seleccionadas.'}${mrBad.length ? '<br>Rango móvil fuera de control: obs. ' + mrBad.join(', ') + '.' : ''}</p>`;
      }
      case 'pareto': {
        const rows = res.categories.map((c, i) => [esc(c), fmt(res.counts[i], 6), fmt(res.percents[i], 3) + '%', fmt(res.cum_percents[i], 3) + '%']);
        return Charts.render(res, r.analysis) + table(rows, ['Categoría', 'Frecuencia', '%', '% acum.']) + `<p class="note">Total: ${fmt(res.total_count, 6)}.</p>`;
      }
      default: return '';
    }
  }

  function renderResults() {
    const box = $('#results');
    box.innerHTML = state.results.map((r) => `<article class="result" data-id="${r.id}">
      <div class="result-head"><h3>${r.title}<small>${esc(r.subtitle)}</small></h3><button class="icon-btn" data-act="delete" aria-label="Eliminar resultado">✕</button></div>
      <div class="result-body">${resultBody(r)}</div>
      <div class="result-actions">${r.result.graph !== 'describe' ? '<button class="btn" data-act="image">Guardar imagen</button>' : ''}<button class="btn" data-act="copy">Copiar tablas</button></div></article>`).join('');
    $('#results-empty').hidden = state.results.length > 0;
    const badge = $('#badge');
    badge.hidden = !state.results.length; badge.textContent = state.results.length;
  }

  $('#results').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-act]');
    if (!b) return;
    const card = b.closest('.result');
    const r = state.results.find((x) => x.id === +card.dataset.id);
    if (b.dataset.act === 'delete') { state.results = state.results.filter((x) => x !== r); renderResults(); }
    else if (b.dataset.act === 'copy') {
      const text = [...card.querySelectorAll('table.kv')].map((t) => [...t.rows].map((row) => [...row.cells].map((c) => c.textContent.trim()).join('\t')).join('\n')).join('\n\n');
      try { await navigator.clipboard.writeText(text); toast('Tablas copiadas.', 'info'); } catch (err) { toast('No se pudo copiar al portapapeles.'); }
    } else if (b.dataset.act === 'image') {
      const svg = card.querySelector('svg.chart');
      if (!svg) { toast('Este resultado no tiene gráfica.'); return; }
      try { await saveSvgAsPng(svg, r); } catch (err) { toast('No se pudo crear la imagen: ' + err.message); }
    }
  });

  // ------------------------------------------------------------------ export chart as PNG
  async function saveSvgAsPng(svg, r) {
    const clone = svg.cloneNode(true);
    const orig = [svg, ...svg.querySelectorAll('*')];
    const copy = [clone, ...clone.querySelectorAll('*')];
    const props = ['fill', 'stroke', 'stroke-width', 'stroke-dasharray', 'stroke-linejoin', 'stroke-linecap', 'font-size', 'font-family', 'fill-opacity', 'opacity'];
    orig.forEach((el, i) => {
      const cs = getComputedStyle(el);
      copy[i].setAttribute('style', props.map((p) => `${p}:${cs.getPropertyValue(p)}`).join(';'));
    });
    const vb = svg.viewBox.baseVal;
    const pad = 28, titleH = 30;
    const bg = getComputedStyle(document.documentElement).getPropertyValue('--surface').trim() || '#fff';
    const fg = getComputedStyle(document.body).color;
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.setAttribute('width', vb.width); clone.setAttribute('height', vb.height);
    const scale = 3;
    const img = new Image();
    const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], { type: 'image/svg+xml' }));
    await new Promise((res, rej) => { img.onload = res; img.onerror = () => rej(new Error('no se pudo renderizar la gráfica')); img.src = url; });
    const canvas = document.createElement('canvas');
    canvas.width = (vb.width + pad) * scale; canvas.height = (vb.height + pad + titleH) * scale;
    const ctx = canvas.getContext('2d');
    ctx.scale(scale, scale);
    ctx.fillStyle = bg; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = fg; ctx.font = '600 14px system-ui, sans-serif';
    ctx.fillText(r.title + (r.subtitle ? ' — ' + r.subtitle : ''), pad / 2, 22);
    ctx.drawImage(img, pad / 2, titleH, vb.width, vb.height);
    URL.revokeObjectURL(url);
    const blob = await new Promise((res) => canvas.toBlob(res, 'image/png'));
    const file = new File([blob], `statcraft-${r.analysis}.png`, { type: 'image/png' });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try { await navigator.share({ files: [file], title: r.title }); return; } catch (err) { if (err.name === 'AbortError') return; }
    }
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = file.name; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  }

  // ------------------------------------------------------------------ tooltips for chart elements
  const tip = $('#tip');
  let tipTimer = null;
  function showTip(el, x, y) {
    tip.textContent = el.getAttribute('data-tip');
    tip.hidden = false;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(8, Math.min(innerWidth - w - 8, x - w / 2)) + 'px';
    tip.style.top = Math.max(8, y - h - 16) + 'px';
    clearTimeout(tipTimer);
    tipTimer = setTimeout(() => { tip.hidden = true; }, 3500);
  }
  document.addEventListener('pointerdown', (e) => { const el = e.target.closest('[data-tip]'); if (el) showTip(el, e.clientX, e.clientY); else tip.hidden = true; });
  document.addEventListener('pointerover', (e) => { if (e.pointerType === 'mouse') { const el = e.target.closest('[data-tip]'); if (el) showTip(el, e.clientX, e.clientY); } });
  document.addEventListener('pointerout', (e) => { if (e.pointerType === 'mouse' && e.target.closest('[data-tip]')) tip.hidden = true; });

  // ------------------------------------------------------------------ navigation
  function switchView(name) {
    document.querySelectorAll('.view').forEach((v) => { v.hidden = v.id !== 'view-' + name; });
    document.querySelectorAll('.tab').forEach((t) => t.setAttribute('aria-selected', String(t.dataset.view === name)));
    $('main').scrollTop = 0;
  }
  document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => switchView(t.dataset.view)));

  // ------------------------------------------------------------------ boot
  const saved = load('sc.data.v1');
  state.columns = Array.isArray(saved) && saved.length ? saved : [newColumn(0), newColumn(1)];
  renderGrid(); renderCatalog(); renderResults();
  startEngine();
  if ('serviceWorker' in navigator && location.protocol.startsWith('http') && !new URLSearchParams(location.search).has('nosw')) {
    navigator.serviceWorker.register('sw.js').catch(() => { /* offline cache is optional */ });
  }
  window.StatCraft = { state, callEngine, switchView, setData, parseTable };  // handy for debugging and tests
})();
