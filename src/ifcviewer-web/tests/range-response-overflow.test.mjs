// This file was generated with the assistance of an AI coding tool.
//
// Spec for the web viewer's HTTP range scratch copy. The tests fail while a
// body longer than the requested window is written past that scratch buffer.
// They pass once every such body is rejected or truncated to the requested
// size before the copy, including status 206 and a 206 body returned through
// the OPFS cache source. A full-file status 200 is still sliced to the window.
//
// Run from the repository root:
//   node --test src/ifcviewer-web/tests/range-response-overflow.test.mjs

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import http from 'node:http';
import { dirname, join } from 'node:path';
import { after, before, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const viewportCorePath = join(repoRoot, 'src/ifcviewer/ViewportCore.cpp');
const viewerJsPath = join(repoRoot, 'src/ifcviewer-web/web/ifcviewer.js');
const viewerHtmlPath = join(repoRoot, 'src/ifcviewer-web/web/IfcViewerWeb.html');

const FILE_SIZE = 8192;
const OFFSET = 100;
const SIZE = 32;
const EXTRA = 128;
const DST = 4096;

// webIssueCurrentPlan sizes the scratch to plan.read_size and passes that same
// count to ifcvReadRangeInto. The heap is larger than the scratch, as the
// viewer's wasm memory is (INITIAL_MEMORY is 256MB); bytes immediately outside
// the scratch stand in for the neighbouring heap allocation.

function pattern(n, start) {
  const out = Buffer.alloc(n);
  for (let i = 0; i < n; i++) out[i] = (start + i * 3 + 1) & 0xff;
  return out;
}

function extractEmJs(source, name) {
  const marker = `EM_JS(void, ${name},`;
  const at = source.indexOf(marker);
  if (at < 0) throw new Error(`missing EM_JS function ${name}`);
  let i = at + marker.length;
  while (source[i] !== '(') i++;
  const paramsStart = i;
  let depth = 0;
  for (; i < source.length; i++) {
    if (source[i] === '(') depth++;
    else if (source[i] === ')') {
      depth--;
      if (depth === 0) { i++; break; }
    }
  }
  const params = source.slice(paramsStart, i);
  while (', \n\r\t'.includes(source[i])) i++;
  if (source[i] !== '{') throw new Error(`${name} body is not a brace block`);
  const bodyStart = i;
  depth = 0;
  let quote = null;
  for (; i < source.length; i++) {
    const c = source[i];
    if (quote) {
      if (c === '\\') { i++; continue; }
      if (c === quote) quote = null;
      continue;
    }
    if (c === '"' || c === "'" || c === '`') { quote = c; continue; }
    if (c === '{') depth++;
    else if (c === '}') {
      depth--;
      if (depth === 0) { i++; break; }
    }
  }
  const body = source.slice(bodyStart, i);
  let args = params.slice(1, -1);
  const argNames = (!args || args.trim() === 'void')
    ? []
    : args.split(',').filter((part) => part.trim()).map((part) => {
      return part.trim().split(/\s+/).pop().replaceAll('*', '');
    });
  // Same wrapping as emscripten's create_em_js: the body is not rewritten.
  const func = `function ${name}(${argNames.join(',')}) ${body}`;
  return { func, argNames };
}

function compileRangeReader(viewportSource) {
  const { func, argNames } = extractEmJs(viewportSource, 'ifcvReadRangeInto');
  for (const name of ['sid', 'reqId', 'offset', 'size', 'dst']) {
    if (!argNames.includes(name)) {
      throw new Error(`ifcvReadRangeInto is missing parameter ${name}`);
    }
  }
  const factory = new Function('Module', 'HEAPU8', `${func}\nreturn ifcvReadRangeInto;`);
  return function bind(Module, heap) {
    const fn = factory(Module, heap);
    return function read(sid, offset, size) {
      heap.fill(0xa5);
      const before = new Uint8Array(heap);
      heap.fill(0, DST, DST + size);
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('range callback timed out')), 3000);
        Module._ifcv_on_range_done = (reqId, ok) => {
          clearTimeout(timer);
          Module._ifcv_on_range_done = () => {};
          const hits = [];
          for (let i = 0; i < heap.length; i++) {
            if (i >= DST && i < DST + size) continue;
            if (heap[i] !== before[i]) hits.push(i);
          }
          resolve({
            ok: ok === 1,
            hits,
            scratch: Buffer.from(heap.subarray(DST, DST + size)),
          });
        };
        const args = argNames.map((name) => {
          if (name === 'sid') return sid;
          if (name === 'reqId') return 1;
          if (name === 'offset') return offset;
          if (name === 'size') return size;
          if (name === 'dst') return DST;
          return 0;
        });
        try {
          fn(...args);
        } catch (err) {
          clearTimeout(timer);
          reject(err);
        }
      });
    };
  };
}

function assertContained(result, body, size) {
  assert.equal(
    result.hits.length,
    0,
    `range body wrote ${result.hits.length} byte(s) outside the ${size}-byte scratch `
    + `(first offset ${result.hits[0]}, ok=${result.ok})`,
  );
  if (result.ok) {
    assert.ok(body.length >= size, 'a successful read returned less than the requested size');
    assert.deepEqual(result.scratch, body.subarray(0, size));
  }
}

const served = [];
let baseUrl = '';

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  const headers = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Range',
    'Access-Control-Expose-Headers': 'Content-Length, Content-Range, ETag, Accept-Ranges',
    ETag: '"v1"',
    'Accept-Ranges': 'bytes',
  };
  if (req.method === 'OPTIONS') {
    res.writeHead(204, headers);
    res.end();
    return;
  }
  if (req.method === 'HEAD') {
    res.writeHead(200, { ...headers, 'Content-Length': String(FILE_SIZE) });
    res.end();
    return;
  }
  const range = req.headers.range || '';
  const match = /^bytes=(\d+)-(\d+)$/.exec(range);
  if (!match) {
    res.writeHead(400, headers);
    res.end();
    return;
  }
  const start = Number(match[1]);
  const end = Number(match[2]);
  const requested = end - start + 1;
  const mode = url.pathname.includes('full')
    ? 'full'
    : url.pathname.includes('exact')
      ? 'exact'
      : 'oversize';
  let status;
  let body;
  if (mode === 'full') {
    status = 200;
    body = pattern(FILE_SIZE, 0);
  } else {
    status = 206;
    const len = requested + (mode === 'oversize' ? EXTRA : 0);
    body = pattern(len, start);
  }
  const extra = {
    'Content-Type': 'application/octet-stream',
    'Content-Length': String(body.length),
  };
  if (status === 206) {
    extra['Content-Range'] = `bytes ${start}-${start + body.length - 1}/${FILE_SIZE}`;
  }
  served.push({ method: 'GET', path: url.pathname, range, status, body });
  res.writeHead(status, { ...headers, ...extra });
  res.end(body);
});

before(async () => {
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  baseUrl = `http://127.0.0.1:${server.address().port}`;
});

after(() => new Promise((resolve, reject) => {
  server.close((err) => (err ? reject(err) : resolve()));
}));

function element() {
  return {
    style: {},
    classList: { add() {}, remove() {}, toggle() {} },
    textContent: '',
    scrollTop: 0,
    scrollHeight: 0,
    value: '',
    disabled: false,
    files: [],
    addEventListener() {},
    click() {},
    getAttribute() { return null; },
  };
}

class MemFile {
  constructor() { this.bytes = Buffer.alloc(0); }
  async getFile() {
    const bytes = this.bytes;
    return { size: bytes.length, text: async () => bytes.toString('utf8') };
  }
  async createWritable() {
    const chunks = [];
    return {
      write: async (data) => {
        chunks.push(Buffer.from(typeof data === 'string' ? data : data));
      },
      close: async () => { this.bytes = Buffer.concat(chunks); },
    };
  }
}

class MemDir {
  constructor() { this.files = new Map(); this.dirs = new Map(); }
  async getDirectoryHandle(name, opts) {
    if (!this.dirs.has(name)) {
      if (!opts || !opts.create) throw new Error('missing directory ' + name);
      this.dirs.set(name, new MemDir());
    }
    return this.dirs.get(name);
  }
  async getFileHandle(name, opts) {
    if (!this.files.has(name)) {
      if (!opts || !opts.create) throw new Error('missing file ' + name);
      this.files.set(name, new MemFile());
    }
    return this.files.get(name);
  }
  async removeEntry(name) { this.files.delete(name); this.dirs.delete(name); }
  keys() { return this.files.keys(); }
}

class CacheWorker {
  postMessage(msg) {
    const send = (data) => { if (this.onmessage) this.onmessage({ data }); };
    if (msg.op === 'open') send({ id: msg.id, ok: true, size: 0 });
    else if (msg.op === 'write' || msg.op === 'close') send({ id: msg.id, ok: true });
    else send({ id: msg.id, ok: false, error: 'unexpected ' + msg.op });
  }
}

function viewerContext({ search, module, onRegistered }) {
  const urlStatics = class extends URL {};
  urlStatics.createObjectURL = () => 'blob:ifcviewer-cache-worker';
  urlStatics.revokeObjectURL = () => {};
  let frames = 0;
  const sandbox = {
    console,
    setTimeout: (fn, ms, ...args) => {
      const timer = setTimeout(fn, ms, ...args);
      if (timer.unref) timer.unref();
      return timer;
    },
    clearTimeout,
    queueMicrotask,
    URL: urlStatics,
    URLSearchParams,
    Blob,
    TextEncoder,
    TextDecoder,
    performance,
    crypto,
    fetch,
    Worker: CacheWorker,
    navigator: {
      gpu: {},
      storage: {
        getDirectory: async () => new MemDir(),
      },
    },
    location: { search },
    document: {
      getElementById: () => element(),
      querySelectorAll: () => [],
      dispatchEvent() {},
    },
    requestAnimationFrame(cb) {
      if (frames++ > 4) return 0;
      const timer = setTimeout(() => cb(performance.now()), 0);
      if (timer.unref) timer.unref();
      return frames;
    },
    createIfcViewer(opts) {
      if (opts.onRuntimeInitialized) opts.onRuntimeInitialized.call(module);
      return Promise.resolve(module);
    },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  module._load_sidecar_from_source_c = (sid) => onRegistered(sid);
  module._clear_scene_c = () => {};
  module._app_ptr = 1;
  module._raf_tick_c = () => {};
  vm.createContext(sandbox);
  vm.runInContext(readFileSync(viewerJsPath, 'utf8'), sandbox, { filename: viewerJsPath });
  return sandbox;
}

function inlinePageScript() {
  const html = readFileSync(viewerHtmlPath, 'utf8');
  const blocks = [];
  const re = /<script(\s[^>]*)?>([\s\S]*?)<\/script>/g;
  for (const match of html.matchAll(re)) {
    if (match[1] && /\bsrc\s*=/.test(match[1])) continue;
    blocks.push(match[2]);
  }
  if (!blocks.length) throw new Error('IfcViewerWeb.html has no inline script');
  return blocks.join('\n');
}

async function loadPageModel(pathname) {
  const heap = new Uint8Array(1 << 16);
  const module = { __ifcvSources: [], HEAPU8: heap };
  const read = compileRangeReader(readFileSync(viewportCorePath, 'utf8'))(module, heap);
  let registered;
  const done = new Promise((resolve) => { registered = resolve; });
  const sandbox = viewerContext({
    search: '?model=' + encodeURIComponent(baseUrl + pathname),
    module,
    onRegistered: (sid) => registered(sid),
  });
  vm.runInContext(inlinePageScript(), sandbox, { filename: viewerHtmlPath });
  const sid = await Promise.race([
    done,
    new Promise((_, reject) => setTimeout(() => reject(new Error('model query did not register a source')), 3000)),
  ]);
  const source = module.__ifcvSources[sid];
  assert.equal(source.url, baseUrl + pathname);
  assert.equal(source.file, null);
  return { read, sid, source };
}

function rangeHeader(offset, size) {
  return `bytes=${offset}-${offset + size - 1}`;
}

function findServed(pathname, offset, size) {
  const want = rangeHeader(offset, size);
  const hits = served.filter((entry) => entry.path === pathname && entry.range === want);
  assert.equal(hits.length, 1, `expected one GET ${pathname} ${want}, saw ${hits.length}`);
  return hits[0];
}

test('status 206 longer than the requested window must not write past the scratch buffer', async () => {
  const path = '/oversize.ifcview';
  const { read, sid } = await loadPageModel(path);
  const result = await read(sid, OFFSET, SIZE);
  const got = findServed(path, OFFSET, SIZE);
  assert.equal(got.status, 206);
  assert.equal(got.body.length, SIZE + EXTRA);
  assertContained(result, got.body, SIZE);
});

test('status 206 of exactly the requested size is copied into the scratch buffer', async () => {
  const path = '/exact.ifcview';
  const { read, sid } = await loadPageModel(path);
  const result = await read(sid, OFFSET, SIZE);
  const got = findServed(path, OFFSET, SIZE);
  assert.equal(got.status, 206);
  assert.equal(got.body.length, SIZE);
  assert.equal(result.ok, true);
  assertContained(result, got.body, SIZE);
});

test('status 200 longer than the window is sliced to that window and stays inside the scratch buffer', async () => {
  const path = '/full.ifcview';
  const { read, sid } = await loadPageModel(path);
  const result = await read(sid, OFFSET, SIZE);
  const got = findServed(path, OFFSET, SIZE);
  assert.equal(got.status, 200);
  assert.ok(got.body.length > SIZE);
  assert.equal(result.ok, true);
  assert.equal(result.hits.length, 0);
  assert.deepEqual(result.scratch, got.body.subarray(OFFSET, OFFSET + SIZE));
});

test('a Blob slice of the requested size still fills only the scratch buffer', async () => {
  const heap = new Uint8Array(1 << 16);
  const payload = pattern(SIZE, OFFSET);
  const blob = new Blob([payload]);
  const module = {
    __ifcvSources: [{ file: blob, url: null, size: blob.size }],
    HEAPU8: heap,
  };
  const read = compileRangeReader(readFileSync(viewportCorePath, 'utf8'))(module, heap);
  const result = await read(0, 0, SIZE);
  assert.equal(result.ok, true);
  assertContained(result, payload, SIZE);
});

test('status 206 longer than the window must not overflow when the OPFS cache source returns it', async () => {
  const path = '/cache-oversize.ifcview';
  const heap = new Uint8Array(1 << 16);
  const module = { __ifcvSources: [], HEAPU8: heap };
  const read = compileRangeReader(readFileSync(viewportCorePath, 'utf8'))(module, heap);
  let registered;
  const done = new Promise((resolve) => { registered = resolve; });
  const sandbox = viewerContext({
    search: '',
    module,
    onRegistered: (sid) => registered(sid),
  });
  const viewer = await sandbox.IfcViewer.create({
    canvas: element(),
    moduleFactory: sandbox.createIfcViewer,
  });
  const sid = await viewer.addUrl(baseUrl + path, { cache: true });
  await done;
  const source = module.__ifcvSources[sid];
  assert.equal(source.url, null);
  assert.equal(typeof source.file.slice, 'function');
  const result = await read(sid, OFFSET, SIZE);
  const got = findServed(path, OFFSET, SIZE);
  assert.equal(got.status, 206);
  assert.equal(got.body.length, SIZE + EXTRA);
  assertContained(result, got.body, SIZE);
});
