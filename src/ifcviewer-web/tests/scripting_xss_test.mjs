// This file was generated with the assistance of an AI coding tool.
//
// Spec for the scripting-page object table. Fails while GlobalId, name, type,
// or the model label are assigned with innerHTML. Passes once those values are
// inserted as text.
//
// The element strings are not literals in this file. A .ifcview is written and
// read with the viewer's sidecar code, encoded with appendJsonString from
// main_web.cpp, and delivered through ifcviewer.js's __ifcvOnObjectsBatch to
// the real renderTable in scripting.html.

import { spawn, execFile } from 'node:child_process';
import { promisify } from 'node:util';
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const execFileAsync = promisify(execFile);
const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '../../..');
const webRoot = path.join(repo, 'src/ifcviewer-web/web');
const mainWeb = path.join(repo, 'src/ifcviewer-web/main_web.cpp');

const payloads = {
    guid: '<img src="x" onerror="window.__xss_guid=1">',
    name: '<img src="x" onerror="window.__xss_name=1">',
    type: '<img src="x" onerror="window.__xss_type=1">',
    model: '<img src="x" onerror="window.__xss_model=1">.ifcview',
};

const benignJson = JSON.stringify([
    { objectId: 1, guid: 'SAMPLE', name: 'Sample wall', type: 'IfcWall', model: 0, sourceId: -1 },
]);

function fail(message) {
    console.error(message);
    process.exitCode = 1;
}

function extractAppendJsonString(src) {
    const start = src.indexOf('void appendJsonString(');
    const end = src.indexOf('\nNavKind classifyPress', start);
    if (start < 0 || end < 0) {
        throw new Error('appendJsonString was not found in main_web.cpp');
    }
    return src.slice(start, end);
}

async function buildEncoder(work) {
    const extracted = extractAppendJsonString(fs.readFileSync(mainWeb, 'utf8'));
    const merged = fs.readFileSync(path.join(here, 'emit_objects_json.cpp'), 'utf8') + '\n' + extracted + '\n';
    const cpp = path.join(work, 'emit.cpp');
    fs.writeFileSync(cpp, merged);
    const bin = path.join(work, 'emit_objects_json');
    const viewer = path.join(repo, 'src/ifcviewer');
    await execFileAsync('g++', [
        '-std=c++17', '-pthread', '-O2',
        '-I', viewer,
        cpp,
        path.join(viewer, 'SidecarCache.cpp'),
        path.join(viewer, 'SidecarCompress.cpp'),
        path.join(viewer, 'StreamingLoader.cpp'),
        '-lzstd',
        '-o', bin,
    ], { cwd: repo });
    return bin;
}

function stubModuleSource() {
    return `
var createIfcViewer = function (opts) {
  var buffer = new ArrayBuffer(65536);
  var raw = {
    HEAPU32: new Uint32Array(buffer),
    HEAPF32: new Float32Array(buffer),
    _malloc: function () { return 256; },
    _free: function () {},
    _app_ptr: 1,
    _raf_tick_c: function () {},
    _projection_is_ortho_c: function () { return 0; },
    _ifcv_get_camera_c: function (ptr) {
      var f = raw.HEAPF32;
      var i = ptr >>> 2;
      for (var k = 0; k < 9; k++) f[i + k] = (k === 3) ? 10 : 0;
    },
    _ifcv_get_selection_c: function () { return 0; },
    _ifcv_get_hidden_c: function () { return 0; },
    _load_sidecar_from_source_c: function () {},
    ccall: function () {},
    __ifcvSources: [],
    _objectCalls: 0,
    _ifcv_request_objects_c: function (token) {
      raw._objectCalls++;
      // One batch per loaded model, matching ifcv_request_objects_c.
      raw.__ifcvOnObjectsBatch(token, window.__BENIGN_JSON);
      if (raw._objectCalls > 1) raw.__ifcvOnObjectsBatch(token, window.__ATTACK_JSON);
      raw.__ifcvOnObjectsDone(token);
    },
  };
  var Module = new Proxy(raw, {
    get: function (target, prop) {
      if (prop in target) return target[prop];
      if (typeof prop === 'string' && prop.charAt(0) === '_') return function () { return 0; };
      return undefined;
    },
  });
  opts.onRuntimeInitialized.call(Module);
  return Promise.resolve(Module);
};
`;
}

function contentType(file) {
    if (file.endsWith('.html')) return 'text/html; charset=utf-8';
    if (file.endsWith('.js')) return 'text/javascript; charset=utf-8';
    return 'application/octet-stream';
}

function startServer(stub) {
    const server = http.createServer((req, res) => {
        const url = new URL(req.url, 'http://127.0.0.1');
        if (url.pathname === '/IfcViewerWeb.js') {
            res.setHeader('content-type', 'text/javascript; charset=utf-8');
            res.end(stub);
            return;
        }
        const rel = decodeURIComponent(url.pathname).replace(/^\/+/, '');
        const file = path.resolve(webRoot, rel);
        if (file !== webRoot && !file.startsWith(webRoot + path.sep)) {
            res.statusCode = 403;
            res.end('forbidden');
            return;
        }
        if (!fs.existsSync(file) || !fs.statSync(file).isFile()) {
            res.statusCode = 404;
            res.end('not found');
            return;
        }
        res.setHeader('content-type', contentType(file));
        res.end(fs.readFileSync(file));
    });
    return new Promise((resolve) => {
        server.listen(0, '127.0.0.1', () => resolve(server));
    });
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForChrome(port) {
    for (let i = 0; i < 50; i++) {
        try {
            const res = await fetch('http://127.0.0.1:' + port + '/json/version');
            if (res.ok) return;
        } catch {
            // Chrome is still starting.
        }
        await sleep(100);
    }
    throw new Error('Chrome did not open a debugging port');
}

class Cdp {
    constructor(ws) {
        this.ws = ws;
        this.next = 0;
        this.pending = new Map();
        this.ws.addEventListener('message', (ev) => {
            const msg = JSON.parse(ev.data);
            if (msg.id && this.pending.has(msg.id)) {
                const { resolve, reject } = this.pending.get(msg.id);
                this.pending.delete(msg.id);
                if (msg.error) reject(new Error(JSON.stringify(msg.error)));
                else resolve(msg.result);
            }
        });
    }
    send(method, params) {
        const id = ++this.next;
        const ws = this.ws;
        return new Promise((resolve, reject) => {
            this.pending.set(id, { resolve, reject });
            ws.send(JSON.stringify({ id, method, params: params || {} }));
        });
    }
}

async function evaluate(cdp, expression) {
    const result = await cdp.send('Runtime.evaluate', {
        expression,
        returnByValue: true,
        awaitPromise: true,
    });
    if (result.exceptionDetails) {
        const text = result.exceptionDetails.text || 'page exception';
        const desc = result.exceptionDetails.exception && result.exceptionDetails.exception.description;
        throw new Error(desc || text);
    }
    return result.result.value;
}

async function main() {
    const work = fs.mkdtempSync(path.join(os.tmpdir(), 'ifcv-xss-'));
    const bin = await buildEncoder(work);
    const { stdout } = await execFileAsync(bin, [
        work, '1', '0', payloads.guid, payloads.name, payloads.type,
    ]);
    const attackJson = stdout.trim();
    const rows = JSON.parse(attackJson);
    if (!Array.isArray(rows) || rows.length !== 1) {
        throw new Error('encoder did not emit one element: ' + attackJson);
    }
    for (const field of ['guid', 'name', 'type']) {
        if (rows[0][field] !== payloads[field]) {
            throw new Error(field + ' changed between the sidecar and JSON.parse: ' + JSON.stringify(rows[0][field]));
        }
    }
    if (!attackJson.includes('<img')) {
        throw new Error('appendJsonString dropped the markup before the page saw it');
    }

    const server = await startServer(stubModuleSource());
    const port = server.address().port;
    const pageUrl = 'http://127.0.0.1:' + port + '/scripting.html';
    const debugPort = 9333;
    const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'ifcv-chrome-'));
    const chrome = spawn('google-chrome', [
        '--headless=new',
        '--no-sandbox',
        '--disable-gpu',
        '--remote-debugging-port=' + debugPort,
        '--user-data-dir=' + profile,
        'about:blank',
    ], { stdio: 'ignore' });

    try {
        await waitForChrome(debugPort);
        const targets = await (await fetch('http://127.0.0.1:' + debugPort + '/json/list')).json();
        const page = targets.find((target) => target.type === 'page');
        if (!page) throw new Error('Chrome has no page target');
        const ws = new WebSocket(page.webSocketDebuggerUrl);
        await new Promise((resolve, reject) => {
            ws.addEventListener('open', resolve);
            ws.addEventListener('error', () => reject(new Error('Chrome websocket failed')));
        });
        const cdp = new Cdp(ws);
        await cdp.send('Page.enable');
        await cdp.send('Runtime.enable');
        await cdp.send('Page.addScriptToEvaluateOnNewDocument', {
            source: [
                'window.__BENIGN_JSON = ' + JSON.stringify(benignJson) + ';',
                'window.__ATTACK_JSON = ' + JSON.stringify(attackJson) + ';',
                'window.__pageErrors = [];',
                'window.addEventListener("error", function (ev) { window.__pageErrors.push(String(ev.message)); });',
            ].join('\n'),
        });
        await cdp.send('Page.navigate', { url: pageUrl });

        let booted = false;
        for (let i = 0; i < 50; i++) {
            booted = await evaluate(cdp, '!!document.querySelector("#object-table tr[data-id=\\"1\\"]")');
            if (booted) break;
            await sleep(100);
        }
        if (!booted) {
            const hint = await evaluate(
                cdp,
                'document.getElementById("scene-hint") && document.getElementById("scene-hint").textContent');
            const errors = await evaluate(cdp, 'window.__pageErrors');
            throw new Error('scripting page did not render the sample row. hint=' +
                hint + ' errors=' + JSON.stringify(errors));
        }

        const ifcview = fs.readFileSync(path.join(work, 'model.ifcview'));
        const openedName = await evaluate(cdp, `(() => {
            const bytes = Uint8Array.from(atob(${JSON.stringify(ifcview.toString('base64'))}), function (c) {
                return c.charCodeAt(0);
            });
            const file = new File([bytes], ${JSON.stringify(payloads.model)}, { type: 'application/octet-stream' });
            const input = document.getElementById('file-input');
            const dt = new DataTransfer();
            dt.items.add(file);
            input.files = dt.files;
            input.dispatchEvent(new Event('change'));
            return input.files[0] && input.files[0].name;
        })()`);
        if (openedName !== payloads.model) {
            throw new Error('file input did not keep the sidecar name');
        }

        let rendered = null;
        for (let i = 0; i < 40; i++) {
            rendered = await evaluate(cdp, `(() => {
                const row = document.querySelector('#object-table tr[data-id="42"]');
                if (!row) return null;
                const cell = (n) => row.children[n] ? row.children[n].textContent : null;
                return {
                    guidText: cell(0),
                    nameText: cell(1),
                    typeText: cell(2),
                    modelText: cell(3),
                    guidFired: window.__xss_guid === 1,
                    nameFired: window.__xss_name === 1,
                    typeFired: window.__xss_type === 1,
                    modelFired: window.__xss_model === 1,
                    imgs: document.querySelectorAll('#object-table img').length,
                    errors: window.__pageErrors,
                };
            })()`);
            if (rendered) break;
            await sleep(100);
        }
        if (!rendered) {
            const errors = await evaluate(cdp, 'window.__pageErrors');
            throw new Error('loaded sidecar never reached the object table. errors=' + JSON.stringify(errors));
        }
        // Event handlers queued by innerHTML run after the element is inserted.
        if (!rendered.guidFired && !rendered.nameFired && !rendered.typeFired && !rendered.modelFired) {
            await sleep(300);
            rendered = await evaluate(cdp, `(() => {
                const row = document.querySelector('#object-table tr[data-id="42"]');
                const cell = (n) => row.children[n] ? row.children[n].textContent : null;
                return {
                    guidText: cell(0),
                    nameText: cell(1),
                    typeText: cell(2),
                    modelText: cell(3),
                    guidFired: window.__xss_guid === 1,
                    nameFired: window.__xss_name === 1,
                    typeFired: window.__xss_type === 1,
                    modelFired: window.__xss_model === 1,
                    imgs: document.querySelectorAll('#object-table img').length,
                    errors: window.__pageErrors,
                };
            })()`);
        }

        const expected = {
            guidText: payloads.guid,
            nameText: payloads.name,
            typeText: payloads.type,
            modelText: payloads.model,
        };
        const problems = [];
        for (const [key, want] of Object.entries(expected)) {
            if (rendered[key] !== want) {
                problems.push(key + ' is ' + JSON.stringify(rendered[key]) + ' wanted ' + JSON.stringify(want));
            }
        }
        for (const field of ['guid', 'name', 'type', 'model']) {
            if (rendered[field + 'Fired']) problems.push(field + ' event handler ran');
        }
        if (rendered.imgs) problems.push(rendered.imgs + ' <img> element(s) in the object table');
        if (problems.length) {
            fail('object table treated sidecar strings as HTML:\n' + problems.join('\n') +
                '\npage errors: ' + JSON.stringify(rendered.errors));
            return;
        }
        console.log('ok: GlobalId, name, type, and model label render as text');
        ws.close();
    } finally {
        chrome.kill('SIGKILL');
        await new Promise((resolve) => server.close(resolve));
    }
}

main().catch((err) => {
    console.error(err && err.stack ? err.stack : err);
    process.exitCode = 1;
});
