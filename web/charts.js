/* StatCraft Web — SVG chart renderers (no dependencies).
 * Every renderer takes an engine result dict and returns an SVG string with a responsive viewBox.
 * Colors come from CSS classes/variables so charts follow light/dark themes. Elements with
 * data-tip="..." show a tooltip on tap/hover (handled in app.js).
 */
const Charts = (() => {
  const W = 360;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function fmt(n, digits = 4) {
    if (n === null || n === undefined || Number.isNaN(n)) return '—';
    if (!Number.isFinite(n)) return n > 0 ? '∞' : '-∞';
    if (n === 0) return '0';
    const a = Math.abs(n);
    if (a >= 1e6 || a < 1e-3) return Number(n.toPrecision(digits)).toExponential(2).replace('e+', 'e');
    return String(Number(n.toPrecision(digits)));
  }

  function niceNum(range, round) {
    const exp = Math.floor(Math.log10(range));
    const f = range / Math.pow(10, exp);
    let nf;
    if (round) nf = f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10;
    else nf = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10;
    return nf * Math.pow(10, exp);
  }

  function niceScale(min, max, target = 5) {
    if (!Number.isFinite(min) || !Number.isFinite(max)) { min = 0; max = 1; }
    if (min === max) { const d = Math.abs(min) * 0.1 || 1; min -= d; max += d; }
    const range = niceNum(max - min, false);
    const step = niceNum(range / (target - 1), true);
    const lo = Math.floor(min / step) * step;
    const hi = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Number(v.toPrecision(12)));
    return { lo, hi, ticks };
  }

  const finite = (arr) => arr.filter((v) => typeof v === 'number' && Number.isFinite(v));

  /** Shared frame: margins, scales, axes, gridlines, titles. */
  function frame({ h = 250, left = 48, right = 14, top = 14, bottom = 40, x, y, xTicks, xLabel = '', yLabel = '', title = '', rightAxis = null }) {
    const iw = W - left - right;
    const ih = h - top - bottom;
    const sx = (v) => left + ((v - x.lo) / (x.hi - x.lo || 1)) * iw;
    const sy = (v) => top + ih - ((v - y.lo) / (y.hi - y.lo || 1)) * ih;
    let s = '';
    for (const t of y.ticks) {
      s += `<line class="grid" x1="${left}" x2="${left + iw}" y1="${sy(t).toFixed(1)}" y2="${sy(t).toFixed(1)}"/>`;
      s += `<text class="tick" x="${left - 6}" y="${(sy(t) + 3.5).toFixed(1)}" text-anchor="end">${fmt(t, 4)}</text>`;
    }
    const xt = xTicks || x.ticks.map((t) => ({ v: t, label: fmt(t, 4) }));
    for (const t of xt) {
      s += `<line class="tickline" x1="${sx(t.v).toFixed(1)}" x2="${sx(t.v).toFixed(1)}" y1="${top + ih}" y2="${top + ih + 4}"/>`;
      s += `<text class="tick" x="${sx(t.v).toFixed(1)}" y="${top + ih + 16}" text-anchor="middle">${esc(t.label)}</text>`;
    }
    if (rightAxis) {
      for (const t of rightAxis.ticks) {
        const yy = top + ih - ((t - rightAxis.lo) / (rightAxis.hi - rightAxis.lo || 1)) * ih;
        s += `<text class="tick" x="${left + iw + 4}" y="${(yy + 3.5).toFixed(1)}">${fmt(t, 4)}${rightAxis.suffix || ''}</text>`;
      }
    }
    s += `<rect class="frame" x="${left}" y="${top}" width="${iw}" height="${ih}"/>`;
    if (xLabel) s += `<text class="axis-title" x="${left + iw / 2}" y="${h - 6}" text-anchor="middle">${esc(xLabel)}</text>`;
    if (yLabel) s += `<text class="axis-title" transform="translate(11 ${top + ih / 2}) rotate(-90)" text-anchor="middle">${esc(yLabel)}</text>`;
    return { svg: s, sx, sy, iw, ih, left, top, h };
  }

  const wrap = (h, body, label) =>
    `<svg class="chart" viewBox="0 0 ${W} ${h}" role="img" aria-label="${esc(label || 'Gráfica')}" preserveAspectRatio="xMidYMid meet">${body}</svg>`;

  const PALETTE = ['var(--c1)', 'var(--c2)', 'var(--c3)', 'var(--c4)', 'var(--c5)', 'var(--c6)'];

  function legend(items, y) {
    let x = 48;
    let s = '';
    items.forEach((it, i) => {
      s += `<circle cx="${x}" cy="${y}" r="3.5" style="fill:${PALETTE[i % PALETTE.length]}"/>`;
      const label = it.length > 16 ? it.slice(0, 15) + '…' : it;
      s += `<text class="tick" x="${x + 7}" y="${y + 3.5}">${esc(label)}</text>`;
      x += 18 + Math.min(it.length, 16) * 5.4;
    });
    return s;
  }

  // ------------------------------------------------------------------ histogram
  function histogram(result) {
    const p = result.panels[0];
    const ser = p.series[0];
    const edges = ser.edges;
    const counts = ser.counts;
    const ymax = Math.max(...counts, 1);
    const x = niceScale(edges[0], edges[edges.length - 1]);
    const y = niceScale(0, ymax * 1.08);
    x.lo = Math.min(x.lo, edges[0]); x.hi = Math.max(x.hi, edges[edges.length - 1]);
    const f = frame({ x, y, xLabel: p.xlabel || '', yLabel: p.ylabel || 'Frecuencia', xTicks: x.ticks.filter((t) => t >= x.lo && t <= x.hi).map((t) => ({ v: t, label: fmt(t, 4) })) });
    let s = f.svg;
    counts.forEach((c, i) => {
      const x0 = f.sx(edges[i]);
      const x1 = f.sx(edges[i + 1]);
      const yy = f.sy(c);
      s += `<rect class="bar" x="${x0.toFixed(1)}" y="${yy.toFixed(1)}" width="${Math.max(x1 - x0 - 1, 0.5).toFixed(1)}" height="${(f.sy(0) - yy).toFixed(1)}" data-tip="[${fmt(edges[i])}, ${fmt(edges[i + 1])}${i === counts.length - 1 ? ']' : ')'}: ${c}"/>`;
    });
    if (ser.curve_x && ser.curve_x.length > 1) {
      const pts = ser.curve_x.map((vx, i) => `${f.sx(vx).toFixed(1)},${f.sy(ser.curve_y[i]).toFixed(1)}`).join(' ');
      s += `<polyline class="line" points="${pts}"/>`;
    }
    return wrap(250, s, 'Histograma de ' + (p.xlabel || ''));
  }

  // ------------------------------------------------------------------ boxplot
  function boxplot(result) {
    const items = result.panels[0].items;
    const all = [];
    items.forEach((it) => { all.push(it.box.low, it.box.high, ...it.box.outliers); });
    const y = niceScale(Math.min(...finite(all)), Math.max(...finite(all)));
    const n = items.length;
    const x = { lo: 0, hi: n, ticks: [] };
    const xTicks = items.map((it, i) => ({ v: i + 0.5, label: (it.label || '').length > 10 ? it.label.slice(0, 9) + '…' : it.label }));
    const f = frame({ x, y, xTicks, yLabel: result.panels[0].ylabel || '', xLabel: result.panels[0].xlabel || '' });
    let s = f.svg;
    const bw = Math.min(40, (f.iw / n) * 0.55);
    items.forEach((it, i) => {
      const cx = f.sx(i + 0.5);
      const b = it.box;
      const col = PALETTE[i % PALETTE.length];
      s += `<line class="whisker" x1="${cx}" x2="${cx}" y1="${f.sy(b.low)}" y2="${f.sy(b.q1)}"/><line class="whisker" x1="${cx}" x2="${cx}" y1="${f.sy(b.q3)}" y2="${f.sy(b.high)}"/>`;
      s += `<line class="whisker" x1="${cx - bw / 4}" x2="${cx + bw / 4}" y1="${f.sy(b.low)}" y2="${f.sy(b.low)}"/><line class="whisker" x1="${cx - bw / 4}" x2="${cx + bw / 4}" y1="${f.sy(b.high)}" y2="${f.sy(b.high)}"/>`;
      s += `<rect class="box" style="fill:${col}" x="${(cx - bw / 2).toFixed(1)}" y="${f.sy(b.q3).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(f.sy(b.q1) - f.sy(b.q3), 1).toFixed(1)}" data-tip="${esc(it.label)} — Q1 ${fmt(b.q1)}, mediana ${fmt(b.median)}, Q3 ${fmt(b.q3)}"/>`;
      s += `<line class="median" x1="${(cx - bw / 2).toFixed(1)}" x2="${(cx + bw / 2).toFixed(1)}" y1="${f.sy(b.median)}" y2="${f.sy(b.median)}"/>`;
      if (typeof it.mean === 'number') s += `<path class="mean" d="M${cx} ${f.sy(it.mean) - 4}l4 4l-4 4l-4 -4z" data-tip="Media ${fmt(it.mean)}"/>`;
      b.outliers.forEach((o) => { s += `<circle class="outlier" cx="${cx}" cy="${f.sy(o).toFixed(1)}" r="3.4" data-tip="Atípico: ${fmt(o)}"/>`; });
    });
    return wrap(250, s, 'Diagrama de caja');
  }

  // ------------------------------------------------------------------ scatter
  function scatter(result) {
    const series = result.series;
    const xs = finite(series.flatMap((s) => s.x));
    const ys = finite(series.flatMap((s) => s.y));
    // The engine returns only intercept/slope per group; draw each line across its own series' x range.
    const fits = (result.fits || []).map((ft) => {
      const k = Math.max(series.findIndex((q) => q.label === ft.group), 0);
      const xv = finite(series[k].x);
      const x0 = Math.min(...xv);
      const x1 = Math.max(...xv);
      return { k, intercept: ft.intercept, slope: ft.slope, x: [x0, x1], y: [ft.intercept + ft.slope * x0, ft.intercept + ft.slope * x1] };
    });
    fits.forEach((ft) => { xs.push(...ft.x); ys.push(...ft.y); });
    const x = niceScale(Math.min(...xs), Math.max(...xs));
    const y = niceScale(Math.min(...ys), Math.max(...ys));
    const multi = series.length > 1;
    const f = frame({ x, y, h: multi ? 268 : 250, xLabel: result.xlabel, yLabel: result.ylabel });
    let s = f.svg;
    series.forEach((ser, k) => {
      const col = PALETTE[k % PALETTE.length];
      if (/connect/.test(result.scatter_mode || '')) {
        s += `<polyline class="line thin" style="stroke:${col}" points="${ser.x.map((vx, i) => `${f.sx(vx).toFixed(1)},${f.sy(ser.y[i]).toFixed(1)}`).join(' ')}"/>`;
      }
      ser.x.forEach((vx, i) => {
        if (vx === null || ser.y[i] === null) return;
        s += `<circle class="dot" style="fill:${col}" cx="${f.sx(vx).toFixed(1)}" cy="${f.sy(ser.y[i]).toFixed(1)}" r="3.6" data-tip="${esc(ser.label)}: (${fmt(vx)}, ${fmt(ser.y[i])})"/>`;
      });
    });
    fits.forEach((ft) => {
      s += `<line class="fitline" style="stroke:${PALETTE[ft.k % PALETTE.length]}" x1="${f.sx(ft.x[0])}" y1="${f.sy(ft.y[0])}" x2="${f.sx(ft.x[1])}" y2="${f.sy(ft.y[1])}" data-tip="y = ${fmt(ft.intercept)} + ${fmt(ft.slope)}·x"/>`;
    });
    if (multi) s += legend(series.map((q) => q.label), 258);
    return wrap(multi ? 268 : 250, s, 'Diagrama de dispersión');
  }

  // ------------------------------------------------------------------ run chart
  function runChart(result) {
    const pts = result.points;
    const x = { lo: 0.5, hi: pts.length + 0.5, ticks: [] };
    const xt = niceScale(1, pts.length, 6).ticks.filter((t) => t >= 1 && t <= pts.length).map((t) => ({ v: t, label: String(t) }));
    const y = niceScale(Math.min(...pts, result.median), Math.max(...pts, result.median));
    const f = frame({ x, y, xTicks: xt, xLabel: result.subgroup_size > 1 ? 'Subgrupo' : 'Observación', yLabel: result.variable_name });
    let s = f.svg;
    s += `<line class="cl" x1="${f.left}" x2="${f.left + f.iw}" y1="${f.sy(result.median)}" y2="${f.sy(result.median)}"/>`;
    s += `<text class="limit-label" x="${f.left + f.iw - 2}" y="${f.sy(result.median) - 4}" text-anchor="end">Mediana ${fmt(result.median)}</text>`;
    s += `<polyline class="line thin" points="${pts.map((v, i) => `${f.sx(i + 1).toFixed(1)},${f.sy(v).toFixed(1)}`).join(' ')}"/>`;
    pts.forEach((v, i) => { s += `<circle class="dot" cx="${f.sx(i + 1).toFixed(1)}" cy="${f.sy(v).toFixed(1)}" r="3.3" data-tip="#${i + 1}: ${fmt(v)}"/>`; });
    return wrap(250, s, 'Gráfica de corridas');
  }

  // ------------------------------------------------------------------ I-MR
  function imr(result) {
    const obs = result.observations;
    const n = obs.length;
    const failures = result.test_failures || {};
    const signalSet = new Set(Object.keys(failures).map(Number));
    const mrSignals = new Set((result.mr_signals || []).map(Number));
    const xt = niceScale(1, n, 6).ticks.filter((t) => t >= 1 && t <= n).map((t) => ({ v: t, label: String(t) }));
    const x = { lo: 0.5, hi: n + 0.5, ticks: [] };

    function panel(values, cl, ucl, lcl, signals, label, h, extra) {
      const lims = [cl, ucl, lcl, ...finite(values)].filter((v) => v !== null && v !== undefined);
      const y = niceScale(Math.min(...lims), Math.max(...lims));
      const f = frame({ x, y, xTicks: xt, h, xLabel: extra.xLabel || '', yLabel: label, left: 48, right: 56, top: 12, bottom: extra.xLabel ? 36 : 22 });
      let s = f.svg;
      const hline = (v, cls, text) => {
        if (v === null || v === undefined) return '';
        return `<line class="${cls}" x1="${f.left}" x2="${f.left + f.iw}" y1="${f.sy(v).toFixed(1)}" y2="${f.sy(v).toFixed(1)}"/><text class="limit-label" x="${f.left + f.iw + 4}" y="${(f.sy(v) + 3.5).toFixed(1)}">${text}</text>`;
      };
      s += hline(ucl, 'limit', 'LCS ' + fmt(ucl, 4)) + hline(cl, 'cl', 'LC ' + fmt(cl, 4)) + hline(lcl, 'limit', 'LCI ' + fmt(lcl, 4));
      const pairs = values.map((v, i) => [i + 1, v]).filter(([, v]) => v !== null && v !== undefined);
      s += `<polyline class="line thin" points="${pairs.map(([i, v]) => `${f.sx(i).toFixed(1)},${f.sy(v).toFixed(1)}`).join(' ')}"/>`;
      pairs.forEach(([i, v]) => {
        const bad = signals.has(i);
        const tip = `#${i}: ${fmt(v)}` + (bad && extra.tests && extra.tests[i] ? ' ⚠ ' + extra.tests[i].map((t) => 'Prueba ' + t).join(', ') : bad ? ' ⚠ fuera de control' : '');
        s += `<circle class="${bad ? 'dot bad' : 'dot'}" cx="${f.sx(i).toFixed(1)}" cy="${f.sy(v).toFixed(1)}" r="${bad ? 4.4 : 3.1}" data-tip="${esc(tip)}"/>`;
      });
      return { s, h };
    }

    const top = panel(obs, result.i_center, result.i_ucl, result.i_lcl, signalSet, 'Individuales', 210, { tests: failures });
    const bottom = panel(result.moving_ranges, result.mr_center, result.mr_ucl, result.mr_lcl, mrSignals, 'Rango móvil', 190, { xLabel: 'Observación' });
    const body = top.s + `<g transform="translate(0 ${top.h})">${bottom.s}</g>`;
    return wrap(top.h + bottom.h, body, 'Gráfica de control I-MR');
  }

  // ------------------------------------------------------------------ Pareto
  function pareto(result) {
    const cats = result.categories;
    const counts = result.counts;
    const cum = result.cum_percents;
    const n = cats.length;
    const y = niceScale(0, Math.max(...counts) * 1.05);
    const x = { lo: 0, hi: n, ticks: [] };
    const xTicks = cats.map((c, i) => ({ v: i + 0.5, label: String(c).length > 7 ? String(c).slice(0, 6) + '…' : String(c) }));
    const right = { lo: 0, hi: 100, ticks: [0, 25, 50, 75, 100], suffix: '%' };
    const f = frame({ x, y, xTicks, h: 270, left: 44, right: 40, bottom: 56, yLabel: 'Frecuencia', rightAxis: right });
    let s = f.svg;
    const slot = f.iw / n;
    counts.forEach((c, i) => {
      const x0 = f.sx(i) + slot * 0.1;
      s += `<rect class="bar" x="${x0.toFixed(1)}" y="${f.sy(c).toFixed(1)}" width="${(slot * 0.8).toFixed(1)}" height="${(f.sy(0) - f.sy(c)).toFixed(1)}" data-tip="${esc(cats[i])}: ${fmt(c)} (${fmt(result.percents[i], 3)}%)"/>`;
    });
    const sr = (p) => f.top + f.ih - (p / 100) * f.ih;
    if (result.show_cumulative !== false) {
      s += `<polyline class="line" points="${cum.map((p, i) => `${f.sx(i + 0.5).toFixed(1)},${sr(p).toFixed(1)}`).join(' ')}"/>`;
      cum.forEach((p, i) => { s += `<circle class="dot" cx="${f.sx(i + 0.5).toFixed(1)}" cy="${sr(p).toFixed(1)}" r="3.2" data-tip="Acumulado: ${fmt(p, 3)}%"/>`; });
    }
    return wrap(270, s.replace(/<text class="tick" x="(\d+\.?\d*)" y="(\d+\.?\d*)" text-anchor="middle">/g, (m, tx, ty) => `<text class="tick" transform="translate(${tx} ${ty}) rotate(-35)" text-anchor="end">`), 'Diagrama de Pareto');
  }

  const renderers = { histogram, boxplot, scatter, run_chart: runChart, imr, pareto };
  function render(result, analysisId) {
    const fn = renderers[analysisId] || renderers[result.graph] || renderers[result.analysis];
    return fn ? fn(result) : '';
  }

  return { render, fmt, esc };
})();
