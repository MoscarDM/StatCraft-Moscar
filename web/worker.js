/* StatCraft Web — computation worker.
 * Runs Pyodide (CPython + NumPy + SciPy in WebAssembly) off the UI thread and exposes the
 * StatCraft engines through sc_web.run(). Messages:
 *   in : {id, analysis, payload}      out: {id, ok, json | error}
 *   out: {type:'status', text, pct}   progress while loading;  {type:'ready'} when usable.
 * `?pyodide=/pyo/` points at a local Pyodide copy (used for offline testing); by default the CDN is used.
 */
const params = new URL(self.location.href).searchParams;
const PYODIDE_URL = params.get('pyodide') || 'https://cdn.jsdelivr.net/pyodide/v0.29.3/full/';
const ENGINE_URL = params.get('engine') || 'engine/engine.zip';

let runPy = null;

function status(text, pct) {
  postMessage({ type: 'status', text, pct });
}

async function init() {
  status('Descargando Python…', 5);
  importScripts(PYODIDE_URL + 'pyodide.js');
  const pyodide = await loadPyodide({ indexURL: PYODIDE_URL });
  status('Cargando NumPy y SciPy…', 35);
  await pyodide.loadPackage(['numpy', 'scipy']);
  status('Cargando motores de StatCraft…', 80);
  const response = await fetch(ENGINE_URL);
  if (!response.ok) throw new Error('No se pudo descargar ' + ENGINE_URL + ' (' + response.status + ')');
  pyodide.unpackArchive(await response.arrayBuffer(), 'zip', { extractDir: '/home/pyodide/app' });
  pyodide.runPython('import sys\nsys.path.insert(0, "/home/pyodide/app")');
  runPy = pyodide.runPython('import sc_web\nsc_web.run');
  status('Listo', 100);
  postMessage({ type: 'ready' });
}

const ready = init().catch((err) => {
  postMessage({ type: 'fatal', error: String(err && err.message ? err.message : err) });
  throw err;
});

self.onmessage = async (event) => {
  const { id, analysis, payload } = event.data;
  try {
    await ready;
    const json = runPy(analysis, JSON.stringify(payload));
    postMessage({ id, ok: true, json });
  } catch (err) {
    postMessage({ id, ok: false, error: String(err && err.message ? err.message : err) });
  }
};
