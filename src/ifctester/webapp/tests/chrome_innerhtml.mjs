// This file was generated with the assistance of an AI coding tool.
// Assigns stdin HTML with element.innerHTML in headless Chrome and prints
// whether an image onerror handler ran. Uses Node's WebSocket, not jsdom's.
import { spawn } from "node:child_process";

const chromePath = process.env.CHROME_PATH ?? "/usr/local/bin/google-chrome";
const marker = process.env.XSS_MARKER ?? "data-executed";
const html = await new Promise((resolve, reject) => {
    const chunks = [];
    process.stdin.on("data", (chunk) => chunks.push(chunk));
    process.stdin.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    process.stdin.on("error", reject);
});

const port = 20000 + Math.floor(Math.random() * 20000);
const chrome = spawn(
    chromePath,
    [
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        `--remote-debugging-port=${port}`,
        "about:blank",
    ],
    { stdio: "ignore" },
);

try {
    let version;
    for (let attempt = 0; attempt < 50; attempt += 1) {
        try {
            version = await fetch(`http://127.0.0.1:${port}/json/version`).then((response) => response.json());
            break;
        } catch {
            await new Promise((resolve) => setTimeout(resolve, 100));
        }
    }
    if (!version?.webSocketDebuggerUrl) {
        throw new Error(`Chrome did not open a debugging port at ${chromePath}`);
    }

    const browser = new WebSocket(version.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
        browser.addEventListener("open", resolve);
        browser.addEventListener("error", () => reject(new Error("Chrome debugging socket failed")));
    });

    let nextId = 0;
    const pending = new Map();
    browser.addEventListener("message", (event) => {
        const message = JSON.parse(String(event.data));
        if (message.id !== undefined && pending.has(message.id)) {
            pending.get(message.id)(message);
            pending.delete(message.id);
        }
    });
    const send = (method, params = {}, sessionId) =>
        new Promise((resolve) => {
            const id = ++nextId;
            pending.set(id, resolve);
            browser.send(JSON.stringify({ id, method, params, sessionId }));
        });

    const created = await send("Target.createTarget", { url: "about:blank" });
    const targetId = created.result?.targetId;
    const attached = await send("Target.attachToTarget", { targetId, flatten: true });
    const sessionId = attached.result?.sessionId;
    const expression = `(() => {
        const host = document.createElement('div');
        document.body.appendChild(host);
        host.innerHTML = ${JSON.stringify(html)};
        return new Promise((resolve) => setTimeout(() => {
            const marker = ${JSON.stringify(marker)};
            const imgs = [...host.querySelectorAll('img')];
            resolve(imgs.some((img) => img.getAttribute(marker) === '1'));
        }, 200));
    })()`;
    const evaluated = await send(
        "Runtime.evaluate",
        { expression, awaitPromise: true, returnByValue: true },
        sessionId,
    );
    const value = evaluated.result?.result?.value;
    if (typeof value !== "boolean") {
        throw new Error(`Chrome evaluation failed: ${JSON.stringify(evaluated)}`);
    }
    process.stdout.write(value ? "true\n" : "false\n");
    browser.close();
} finally {
    chrome.kill("SIGKILL");
}
