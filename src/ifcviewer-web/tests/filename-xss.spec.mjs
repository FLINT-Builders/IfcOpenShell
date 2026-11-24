// This file was generated with the assistance of an AI coding tool.
//
// Spec for the embedded viewer's model-name XSS. The assertions fail while
// embedded.html (and the scripting page's model column) assign the name with
// innerHTML, and pass once that name is inserted as text.
//
// IfcViewerWeb.js is not the wasm build. The name never enters the module:
// addFile() returns as soon as load_sidecar_from_source_c returns, and that
// function does not read the file name (src/ifcviewer-web/main_web.cpp). The
// pages under test and ifcviewer.js are the real files in web/.

import { test, expect } from '@playwright/test';
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../web');
const SIDECAR = Buffer.from('sidecar-bytes');

// Enough of the wasm factory for IfcViewer.create() to resolve and for
// addFile/addUrl to return a source id. Object batches follow
// ifcv_request_objects_c: one JSON array per model index, sample at 0,
// then each file passed to addFile. Names in those batches are fixed; the
// file name under test is stored by the page, not by this stand-in.
const WASM_FACTORY = `
globalThis.createIfcViewer = function (opts) {
  const Module = {
    _app_ptr: 1,
    canvas: opts && opts.canvas,
    _raf_tick_c: function () {},
    _malloc: function () { return 0; },
    _free: function () {},
    _load_sidecar_from_source_c: function () {},
    _clear_scene_c: function () {},
    _ifcv_model_count_c: function () { return 0; },
    _ifcv_model_resident_c: function () { return 0; },
    _ifcv_model_total_c: function () { return 1; },
    _ifcv_model_vram_bytes_c: function () { return 0; },
    _ifcv_get_frame_stats_c: function () { return 0; },
    _ifcv_unload_model_c: function () {},
    _ifcv_load_model_c: function () { return 1; },
    _ifcv_model_unloaded_c: function () { return 0; },
    _ifcv_get_camera_c: function () {},
    _projection_is_ortho_c: function () { return 0; },
    _ifcv_get_hidden_c: function () { return 0; },
    _ifcv_get_selection_c: function () { return 0; },
    _ifcv_get_active_object_c: function () { return 0; },
    _ifcv_request_objects_c: function (token) {
      const sources = Module.__ifcvSources || [];
      const batches = [
        '[{"objectId":1,"model":0,"sourceId":-1,"guid":"SAMPLEGUID","name":"Slab","type":"IfcSlab"}]'
      ];
      sources.forEach(function (_, i) {
        const model = i + 1;
        batches.push(
          '[{"objectId":' + (10 + i) + ',"model":' + model + ',"sourceId":' + i +
          ',"guid":"USERGUID","name":"Wall","type":"IfcWall"}]');
      });
      batches.forEach(function (json) {
        if (Module.__ifcvOnObjectsBatch) Module.__ifcvOnObjectsBatch(token, json);
      });
      if (Module.__ifcvOnObjectsDone) Module.__ifcvOnObjectsDone(token);
    },
    HEAPF64: new Float64Array(32),
    HEAPF32: new Float32Array(32),
    __ifcvSources: [],
  };
  return new Promise(function (resolve) {
    setTimeout(function () {
      if (opts.onRuntimeInitialized) opts.onRuntimeInitialized.call(Module);
      resolve(Module);
    }, 0);
  });
};
`;

let origin;
let server;

async function readWeb(name) {
  return readFile(path.join(WEB, name));
}

test.beforeAll(async () => {
  server = http.createServer(async (req, res) => {
    try {
      const url = new URL(req.url, 'http://127.0.0.1');
      const pathname = decodeURIComponent(url.pathname);
      if (pathname === '/IfcViewerWeb.js') {
        res.writeHead(200, { 'Content-Type': 'text/javascript; charset=utf-8' });
        res.end(WASM_FACTORY);
        return;
      }
      if (pathname === '/embedded.html' || pathname === '/scripting.html' || pathname === '/ifcviewer.js') {
        const body = await readWeb(pathname.slice(1));
        const type = pathname.endsWith('.js') ? 'text/javascript; charset=utf-8' : 'text/html; charset=utf-8';
        res.writeHead(200, { 'Content-Type': type, 'Content-Length': body.length });
        res.end(body);
        return;
      }
      // Any other path is a sidecar, so addUrl() can size a URL whose last
      // segment contains markup. HEAD Content-Length is what ifcviewer.js sizeUrl reads.
      if (req.method === 'HEAD') {
        res.writeHead(200, {
          'Content-Type': 'application/octet-stream',
          'Content-Length': SIDECAR.length,
          'Accept-Ranges': 'bytes',
        });
        res.end();
        return;
      }
      res.writeHead(200, {
        'Content-Type': 'application/octet-stream',
        'Content-Length': SIDECAR.length,
        'Accept-Ranges': 'bytes',
      });
      res.end(SIDECAR);
    } catch (err) {
      res.writeHead(500);
      res.end(String(err && err.message || err));
    }
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  origin = `http://127.0.0.1:${port}`;
});

test.afterAll(async () => {
  if (server) await new Promise((resolve) => server.close(resolve));
});

async function openEmbedded(page) {
  await page.goto(origin + '/embedded.html');
  await page.waitForFunction(() => {
    const browse = document.getElementById('browse-btn');
    const url = document.getElementById('url-btn');
    return browse && url && !browse.disabled && !url.disabled;
  });
}

test('file name chosen in the embedded viewer is shown as text', async ({ page }) => {
  const payload =
    '"><img src=x onerror="window.__xss={names:models.map(function(m){return m.name}),api:typeof activeViewer.getObjects}">';
  const malicious = payload + '.ifcview';

  await openEmbedded(page);
  const [chooser] = await Promise.all([
    page.waitForEvent('filechooser'),
    page.locator('#browse-btn').click(),
  ]);
  await chooser.setFiles([
    { name: 'already-open.ifcview', mimeType: 'application/octet-stream', buffer: Buffer.from('a') },
    { name: malicious, mimeType: 'application/octet-stream', buffer: Buffer.from('b') },
  ]);

  await expect(page.locator('#model-list li')).toHaveCount(2);
  const stolen = await page.evaluate(() => window.__xss ?? null);
  expect(stolen).toBeNull();

  const labels = page.locator('#model-list b');
  await expect(labels.nth(0)).toHaveText('already-open.ifcview');
  await expect(labels.nth(1)).toHaveText(malicious);
  await expect(labels.nth(1)).toHaveAttribute('title', malicious);
  expect(await page.locator('#model-list img, #model-list svg, #model-list iframe').count()).toBe(0);

  // Unload runs renderList again with the same stored name.
  await page.locator('#model-list li').nth(1).locator('button').click();
  await expect(labels.nth(1)).toHaveText(malicious);
  await expect(labels.nth(1)).toHaveAttribute('title', malicious);
  expect(await page.evaluate(() => window.__xss ?? null)).toBeNull();
});

test('URL path segment added in the embedded viewer is shown as text', async ({ page }) => {
  const segment = '<img src=x onerror=window.__xss=1>.ifcview';
  await openEmbedded(page);
  await page.locator('#url-input').fill(origin + '/library/' + segment);
  await page.locator('#url-btn').click();

  const label = page.locator('#model-list b');
  await expect(label).toHaveCount(1);
  const stolen = await page.evaluate(() => window.__xss ?? null);
  expect(stolen).toBeNull();
  await expect(label).toHaveText(segment);
  await expect(label).toHaveAttribute('title', segment);
  expect(await page.locator('#model-list img, #model-list svg, #model-list iframe').count()).toBe(0);
});

test('URL with an empty last segment is shown as text', async ({ page }) => {
  // split('/').pop() is empty, so the page uses the whole URL as the name.
  const url = origin + '/<img src=x onerror=window.__xss=1>.ifcview/';
  await openEmbedded(page);
  await page.locator('#url-input').fill(url);
  await page.locator('#url-btn').click();

  const label = page.locator('#model-list b');
  await expect(label).toHaveCount(1);
  const stolen = await page.evaluate(() => window.__xss ?? null);
  expect(stolen).toBeNull();
  await expect(label).toHaveText(url);
  await expect(label).toHaveAttribute('title', url);
  expect(await page.locator('#model-list img, #model-list svg, #model-list iframe').count()).toBe(0);
});

test('file name in the scripting object table is shown as text', async ({ page }) => {
  const payload =
    '"><img src=x onerror="window.__xss={guid:document.querySelector(\'#object-table .mono\').textContent,api:typeof window.viewer.getObjects}">';
  const malicious = payload + '.ifcview';

  await page.goto(origin + '/scripting.html');
  await expect(page.locator('#object-table tbody tr')).toHaveCount(1, { timeout: 10_000 });

  const [chooser] = await Promise.all([
    page.waitForEvent('filechooser'),
    page.locator('#browse-btn').click(),
  ]);
  await chooser.setFiles({
    name: malicious,
    mimeType: 'application/octet-stream',
    buffer: Buffer.from('c'),
  });

  await expect(page.locator('#object-table tbody tr')).toHaveCount(2, { timeout: 10_000 });
  const cell = page.locator('#object-table tbody tr').nth(1).locator('td').nth(3);
  const stolen = await page.evaluate(() => window.__xss ?? null);
  expect(stolen).toBeNull();
  await expect(cell).toHaveText(malicious);
  expect(await page.locator('#object-table img, #object-table svg, #object-table iframe').count()).toBe(0);
  // The sample model's GlobalId stays text in its own cell.
  await expect(page.locator('#object-table .mono').first()).toHaveText('SAMPLEGUID');
});
