# StatCraft Web (móvil) — notas de progreso

Rama: `web-mobile` (fork MoscarDM/StatCraft-Moscar). Objetivo: versión que corre **en el navegador del celular**
reutilizando los motores Python de StatCraft con **Pyodide** (sin servidor, datos locales, funciona sin conexión).

## Decisiones (acordadas con Oscar)
- Arquitectura: **Pyodide** (Python en WebAssembly) + sitio estático (GitHub Pages desde el fork).
- Alcance MVP ("Núcleo"): hoja de datos táctil, estadísticas descriptivas, histograma, boxplot, dispersión,
  Run Chart, I-MR y Pareto. Después: regresión/capacidad/gráficas P-C (etapas posteriores).
- Gráficas: SVG propio en JS (las originales usan QPainter y no se pueden reutilizar). Sin librerías pesadas.

## Hallazgos técnicos
- Los motores (`imr_engine`, `run_chart`, `pareto_engine`, `histograms`, `scatter`, `boxplot_graphs`, `analyses`)
  NO dependen de Qt; `statcraft/__init__.py` es trivial. Probado importando con PySide6/matplotlib bloqueados.
- Pyodide 0.29.x trae NumPy 2.2.5 + SciPy 1.14.1 (misma SciPy que fijamos en el fork para el PC de Oscar).
- jsdelivr/cdnjs están bloqueados desde el servidor de desarrollo; npm y GitHub no. Para probar en local se
  descargó el tarball de GitHub `pyodide-0.29.3.tar.bz2` (se sirve en local con `?pyodide=/pyo/`).
- Resultados de los motores = dicts JSON-serializables (el adaptador limpia NaN/inf/numpy).

## Estructura
- `web/py/sc_web.py` — adaptador sin Qt: `run(analysis, payload_json) -> json`.
- `scripts/build_web.py` — empaqueta el cierre de imports de `statcraft` + adaptador en `web/engine/engine.zip`
  (no se versiona; lo genera el workflow/el script).
- `web/` (pendiente) — `index.html`, `app.js`, `charts.js`, `worker.js`, `style.css`, `sw.js`, `manifest.webmanifest`.

## Estado
- [x] Exploración de motores y formato de resultados
- [x] Adaptador Python + empaquetador (probado en CPython con Qt bloqueado: 7/7 análisis OK)
- [x] Probar el adaptador dentro de Pyodide real (navegador headless): 7/7 OK, arranque ~3.6 s, datos idénticos a CPython
- [~] Interfaz móvil escrita (index.html, style.css, app.js, charts.js, samples.js, worker.js); probando en emulación Pixel 7 (/tmp/claude-0/ui.js). Pendiente: revisar capturas de cada gráfica y corregir fallos
- [~] Gráficas SVG escritas; corregidos: ajuste de regresión (calcular extremos en JS), búsqueda por id de análisis (I-MR no se dibujaba), frecuencia por defecto en Pareto
- [ ] PWA (manifest + service worker) y workflow de GitHub Pages
- [ ] Verificación con emulación de celular (capturas) y datos de prueba `StatCraft_datos_de_prueba.xlsx`

## Cómo continuar
1. `python scripts/build_web.py`
2. Servir `web/` en local (`python -m http.server -d web 8000`) y abrir con un viewport móvil.
3. Seguir el checklist de "Estado".
