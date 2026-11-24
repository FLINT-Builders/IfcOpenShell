// This file was generated with the assistance of an AI coding tool.
//
// These tests exercise the IFC AI chat page's real assistant-message renderer.
// They fail while nested @@MDn@@ placeholders can break out of an href into an
// event handler, and they pass once that output is safe.
//
// Run:
//   node --test tests/ifcchat/markdown_placeholder_xss.test.mjs
//
// Requires Google Chrome (or Chromium) on PATH or at /usr/local/bin/google-chrome.
// The page is served over http because sanitizeUrl() allows only http, https,
// and mailto, so a file:// document would reject the relative placeholder URL
// before the bug is reached.

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "../..");
const APP_DIR = path.join(REPO, "src/ifcchat");
const API_KEY = "placeholder-not-a-key";

// Same shape as the reported breakout. The first link's URL is the next
// placeholder token, which sanitizeUrl() accepts as a relative http(s) URL.
// The second link's generated markup is then substituted inside that href.
const FINDING_PAYLOAD =
    "[notes](@@MD1@@) [src](https://a.b/onmouseover=location='javascript:alert%281%29'//)";

function handlerPayload(attribute) {
    return `[notes](@@MD1@@) [src](https://a.b/${attribute}=window.__ifcchatStolen=apiKey.value//)`;
}

const BLOCKS = [
    { name: "paragraph", text: (payload) => payload },
    { name: "heading", text: (payload) => `# ${payload}` },
    { name: "blockquote", text: (payload) => `> ${payload}` },
    { name: "unordered list", text: (payload) => `- ${payload}` },
    { name: "ordered list", text: (payload) => `1. ${payload}` },
];

const WORKER_STUB = `
self.onmessage = (ev) => {
    const { id, type, payload } = ev.data || {};
    if (type === "init") {
        self.postMessage({ id, ok: true, result: "ok" });
        return;
    }
    if (type === "toolCall") {
        const name = payload && payload.name;
        if (name === "ifc_summary") {
            // Shape of ifcquery 0.8.5 summary.summary's project block.
            // The name is attacker-controlled IFC text; this stub supplies it
            // so the test can follow the app's tool-result forwarding without
            // downloading Pyodide.
            self.postMessage({
                id,
                ok: true,
                result: {
                    schema: "IFC4",
                    total_entities: 1,
                    project: { id: 1, name: ${JSON.stringify(handlerPayload("onmouseover"))}, description: "planted" },
                },
            });
            return;
        }
        self.postMessage({ id, ok: true, result: { ok: true } });
        return;
    }
    self.postMessage({ id, ok: true, result: "ok" });
};
`;

function contentType(filePath) {
    if (filePath.endsWith(".html")) return "text/html; charset=utf-8";
    if (filePath.endsWith(".js") || filePath.endsWith(".mjs")) return "text/javascript; charset=utf-8";
    if (filePath.endsWith(".css")) return "text/css; charset=utf-8";
    return "application/octet-stream";
}

function startServer(state) {
    const server = http.createServer((req, res) => {
        const url = new URL(req.url, "http://127.0.0.1");
        if (req.method === "POST" && url.pathname === "/v1/chat/completions") {
            let body = "";
            req.on("data", (chunk) => {
                body += chunk;
            });
            req.on("end", () => {
                let parsed = {};
                try {
                    parsed = JSON.parse(body);
                } catch {
                    parsed = {};
                }
                state.requests.push(parsed);
                const outcome = state.respond(parsed);
                const status = outcome.status ?? 200;
                res.writeHead(status, { "Content-Type": "application/json" });
                res.end(typeof outcome.body === "string" ? outcome.body : JSON.stringify(outcome.body));
            });
            return;
        }

        if (url.pathname === "/ifc_worker.js") {
            res.writeHead(200, { "Content-Type": "text/javascript; charset=utf-8" });
            res.end(WORKER_STUB);
            return;
        }

        const relative = decodeURIComponent(url.pathname === "/" ? "/index.html" : url.pathname);
        const filePath = path.normalize(path.join(APP_DIR, relative));
        if (!filePath.startsWith(APP_DIR + path.sep) && filePath !== path.join(APP_DIR, "index.html")) {
            res.writeHead(403);
            res.end("forbidden");
            return;
        }
        fs.readFile(filePath, (error, data) => {
            if (error) {
                res.writeHead(404);
                res.end("not found");
                return;
            }
            res.writeHead(200, { "Content-Type": contentType(filePath) });
            res.end(data);
        });
    });
    return new Promise((resolve) => {
        server.listen(0, "127.0.0.1", () => {
            const { port } = server.address();
            resolve({ server, port });
        });
    });
}

function assistantMessage(content) {
    return { choices: [{ message: { role: "assistant", content } }] };
}

class Page {
    constructor(ws) {
        this.ws = ws;
        this.id = 0;
        this.pending = new Map();
        this.dialogs = [];
        ws.addEventListener("message", (ev) => {
            const msg = JSON.parse(ev.data);
            if (msg.method === "Page.javascriptDialogOpening") {
                this.dialogs.push(msg.params.message);
                this.send("Page.handleJavaScriptDialog", { accept: true }).catch(() => {});
            }
            if (msg.id && this.pending.has(msg.id)) {
                this.pending.get(msg.id)(msg);
                this.pending.delete(msg.id);
            }
        });
    }

    send(method, params = {}) {
        const id = ++this.id;
        return new Promise((resolve, reject) => {
            const timer = setTimeout(() => reject(new Error(`timeout ${method}`)), 10000);
            this.pending.set(id, (msg) => {
                clearTimeout(timer);
                if (msg.error) reject(new Error(`${method}: ${JSON.stringify(msg.error)}`));
                else resolve(msg.result);
            });
            this.ws.send(JSON.stringify({ id, method, params }));
        });
    }

    async evaluate(expression) {
        const result = await this.send("Runtime.evaluate", {
            expression,
            returnByValue: true,
            awaitPromise: true,
        });
        if (result.exceptionDetails) {
            throw new Error(result.exceptionDetails.text || "evaluation failed");
        }
        return result.result?.value;
    }
}

function chromeBinary() {
    const candidates = [
        process.env.CHROME_PATH,
        "/usr/local/bin/google-chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ].filter(Boolean);
    for (const candidate of candidates) {
        if (fs.existsSync(candidate)) return candidate;
    }
    return "google-chrome";
}

async function launchChrome() {
    const profile = fs.mkdtempSync(path.join("/tmp", "ifcchat-xss-"));
    const chrome = spawn(
        chromeBinary(),
        [
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--disable-extensions",
            "--window-size=1400,1000",
            "--remote-debugging-port=9333",
            `--user-data-dir=${profile}`,
            "about:blank",
        ],
        { stdio: ["ignore", "pipe", "pipe"] }
    );
    let log = "";
    chrome.stderr.on("data", (chunk) => {
        log += chunk.toString();
    });
    chrome.stdout.on("data", (chunk) => {
        log += chunk.toString();
    });
    const deadline = Date.now() + 10000;
    let version;
    while (Date.now() < deadline) {
        try {
            const response = await fetch("http://127.0.0.1:9333/json/version");
            if (response.ok) {
                version = await response.json();
                break;
            }
        } catch {
            // Chrome is still starting.
        }
        await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (!version) {
        chrome.kill("SIGKILL");
        throw new Error(`Chrome did not open a debugging port.\n${log}`);
    }
    return { chrome, profile };
}

async function openPage() {
    const created = await fetch("http://127.0.0.1:9333/json/new?about:blank", { method: "PUT" });
    if (!created.ok) {
        throw new Error(`unable to open a tab: ${created.status}`);
    }
    const tab = await created.json();
    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await once(ws, "open");
    const page = new Page(ws);
    await page.send("Page.enable");
    await page.send("Runtime.enable");
    return { page, ws, targetId: tab.id };
}

async function loadChat(page, port) {
    await page.send("Page.navigate", { url: `http://127.0.0.1:${port}/index.html` });
    const deadline = Date.now() + 8000;
    let status = "";
    while (Date.now() < deadline) {
        status = await page.evaluate("document.getElementById('status')?.textContent || ''");
        if (status === "Ready") break;
        await new Promise((resolve) => setTimeout(resolve, 50));
    }
    assert.equal(status, "Ready", "chat page did not finish booting");
    await page.evaluate(`
        document.getElementById('apiKey').value = ${JSON.stringify(API_KEY)};
        document.getElementById('baseUrl').value = ${JSON.stringify(`http://127.0.0.1:${port}/v1`)};
        window.__ifcchatStolen = undefined;
        window.__ifcchatAlerts = [];
        window.alert = (value) => { window.__ifcchatAlerts.push(String(value)); };
    `);
}

async function sendPrompt(page, prompt) {
    const before = await page.evaluate("document.querySelectorAll('.msg.assistant .bubble').length");
    await page.evaluate(`
        document.getElementById('input').value = ${JSON.stringify(prompt)};
        document.getElementById('send').click();
    `);
    const deadline = Date.now() + 8000;
    let count = before;
    while (Date.now() < deadline) {
        count = await page.evaluate("document.querySelectorAll('.msg.assistant .bubble').length");
        if (count > before) break;
        await new Promise((resolve) => setTimeout(resolve, 50));
    }
    assert.ok(count > before, "assistant reply was not rendered");
    return count - 1;
}

async function activationEffects(page, bubbleIndex) {
    const points = await page.evaluate(`(() => {
        const bubble = document.querySelectorAll('.msg.assistant .bubble')[${bubbleIndex}];
        bubble.scrollIntoView({ block: 'center' });
        const described = [];
        for (const el of bubble.querySelectorAll('*')) {
            const handlers = [...el.attributes]
                .filter((attr) => attr.name.startsWith('on'))
                .map((attr) => ({ name: attr.name, value: attr.value }));
            if (handlers.length) {
                const rect = el.getBoundingClientRect();
                described.push({ handlers, x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 });
            }
        }
        const links = [...bubble.querySelectorAll('a')].map((el) => ({
            href: el.getAttribute('href'),
            text: el.textContent,
            handlers: [...el.attributes].filter((attr) => attr.name.startsWith('on')).map((attr) => attr.name),
        }));
        return { described, links };
    })()`);

    for (const point of points.described) {
        const firesClick = point.handlers.some((handler) => handler.name === "onclick");
        const firesHover = point.handlers.some((handler) => handler.name === "onmouseover");
        if (firesHover) {
            await page.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 1, y: 1 });
            await page.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: point.x, y: point.y });
        }
        if (firesClick) {
            await page.send("Input.dispatchMouseEvent", {
                type: "mousePressed",
                x: point.x,
                y: point.y,
                button: "left",
                clickCount: 1,
            });
            await page.send("Input.dispatchMouseEvent", {
                type: "mouseReleased",
                x: point.x,
                y: point.y,
                button: "left",
                clickCount: 1,
            });
        }
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
    const stolen = await page.evaluate("window.__ifcchatStolen");
    const alerts = await page.evaluate("window.__ifcchatAlerts.slice()");
    return { ...points, stolen: stolen ?? null, alerts, dialogs: page.dialogs.splice(0) };
}

const state = {
    requests: [],
    respond: () => ({ body: assistantMessage("ok") }),
};

let server;
let port;
let chromeProc;
let profile;

test.before(async () => {
    ({ server, port } = await startServer(state));
    const launched = await launchChrome();
    chromeProc = launched.chrome;
    profile = launched.profile;
});

test.after(async () => {
    server?.close();
    chromeProc?.kill("SIGKILL");
    if (profile) fs.rmSync(profile, { recursive: true, force: true });
});

async function freshPage() {
    const opened = await openPage();
    await loadChat(opened.page, port);
    return opened;
}

test("nested placeholder links in every inline block become hover handlers", async () => {
    const payload = handlerPayload("onmouseover");
    const reply = [...BLOCKS.map((block) => block.text(payload)), "", "[docs](https://example.com/docs)"].join("\n");
    state.requests = [];
    state.respond = () => ({ body: assistantMessage(reply) });
    const { page, ws } = await freshPage();
    try {
        const index = await sendPrompt(page, "What is the element called?");
        const effect = await activationEffects(page, index);
        const safe = effect.links.find((link) => link.href === "https://example.com/docs");
        assert.ok(safe, `ordinary https link was not preserved: ${JSON.stringify(effect.links)}`);
        assert.deepEqual(safe.handlers, []);
        assert.equal(
            effect.stolen,
            null,
            `hovering rendered assistant markdown read the API key field from handlers ${JSON.stringify(effect.described)}`
        );
        assert.deepEqual(
            effect.described,
            [],
            "assistant markdown created event-handler attributes from placeholder expansion"
        );
    } finally {
        ws.close();
    }
});

test("click handler injected the same way reads the API key field", async () => {
    state.requests = [];
    state.respond = () => ({ body: assistantMessage(handlerPayload("onclick")) });
    const { page, ws } = await freshPage();
    try {
        const index = await sendPrompt(page, "What is the element called?");
        const effect = await activationEffects(page, index);
        assert.equal(
            effect.stolen,
            null,
            `clicking the rendered link read the API key field: ${JSON.stringify(effect.described)}`
        );
        assert.deepEqual(effect.described, []);
    } finally {
        ws.close();
    }
});

test("reported javascript URL payload runs when the link is hovered", async () => {
    state.requests = [];
    state.respond = () => ({ body: assistantMessage(FINDING_PAYLOAD) });
    const { page, ws } = await freshPage();
    try {
        const index = await sendPrompt(page, "Repeat the note from the model.");
        const effect = await activationEffects(page, index);
        assert.deepEqual(effect.alerts, [], `hover ran script: ${JSON.stringify(effect)}`);
        assert.deepEqual(effect.dialogs, []);
        assert.deepEqual(effect.described, []);
    } finally {
        ws.close();
    }
});

test("provider error text is rendered through the same assistant sink", async () => {
    state.requests = [];
    state.respond = () => ({ status: 500, body: handlerPayload("onmouseover") });
    const { page, ws } = await freshPage();
    try {
        const index = await sendPrompt(page, "Summarize the model.");
        const effect = await activationEffects(page, index);
        assert.equal(effect.stolen, null, `error bubble ran the planted handler: ${JSON.stringify(effect.described)}`);
        assert.deepEqual(effect.described, []);
    } finally {
        ws.close();
    }
});

test("tool results forwarded to the model are executable when echoed", async () => {
    state.requests = [];
    state.respond = (request) => {
        const tool = (request.messages || []).find((message) => message.role === "tool");
        if (!tool) {
            return {
                body: {
                    choices: [
                        {
                            message: {
                                role: "assistant",
                                tool_calls: [
                                    {
                                        id: "call_summary",
                                        type: "function",
                                        function: { name: "ifc_summary", arguments: "{}" },
                                    },
                                ],
                            },
                        },
                    ],
                },
            };
        }
        const planted = handlerPayload("onmouseover");
        assert.ok(
            String(tool.content).includes(planted),
            "tool result containing the planted IFC name was not sent back to the model"
        );
        return { body: assistantMessage(planted) };
    };
    const { page, ws } = await freshPage();
    try {
        const index = await sendPrompt(page, "Summarize the model.");
        const toolHandlers = await page.evaluate(
            "document.querySelectorAll('.msg.tool [onmouseover], .msg.tool [onclick]').length"
        );
        assert.equal(toolHandlers, 0, "tool bubbles must stay text");
        const effect = await activationEffects(page, index);
        assert.equal(
            effect.stolen,
            null,
            `echoed tool text became a handler: ${JSON.stringify(effect.described)}`
        );
        assert.deepEqual(effect.described, []);
    } finally {
        ws.close();
    }
});

test("a javascript URL written directly in a link is not runnable", async () => {
    state.requests = [];
    state.respond = () => ({ body: assistantMessage("[x](javascript:alert(1))") });
    const { page, ws } = await freshPage();
    try {
        const index = await sendPrompt(page, "Show the link.");
        const effect = await activationEffects(page, index);
        const javascriptLinks = effect.links.filter((link) =>
            (link.href || "").toLowerCase().startsWith("javascript:")
        );
        assert.deepEqual(javascriptLinks, []);
        assert.deepEqual(effect.alerts, []);
        assert.deepEqual(effect.described, []);
    } finally {
        ws.close();
    }
});
