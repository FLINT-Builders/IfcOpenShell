// This file was generated with the assistance of an AI coding tool.
// Drives the IfcTester web worker with the document produced by ids_from_xml_string.
// Autocomplete values are taken from the functions in RestrictionEditor.svelte.

import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const webapp = path.resolve(here, "../webapp");
const require = createRequire(path.join(webapp, "package.json"));
const esbuild = require("esbuild");

const restrictionEditor = path.join(webapp, "src/pages/Home/RestrictionEditor.svelte");
const idsModule = path.join(webapp, "src/modules/api/ids.svelte.ts");
const apiTs = path.join(webapp, "src/modules/wasm/worker/api.ts");
const evalScript = path.join(here, "webapp_python_injection_eval.py");

function extractDeclaration(source, name) {
    const patterns = [`function ${name}(`, `const ${name} =`];
    let start = -1;
    for (const pattern of patterns) {
        start = source.indexOf(pattern);
        if (start !== -1) break;
    }
    if (start < 0) throw new Error(`Could not find ${name}`);
    const brace = source.indexOf("{", start);
    let depth = 0;
    let quote = null;
    for (let i = brace; i < source.length; i++) {
        const char = source[i];
        if (quote) {
            if (char === "\\") {
                i += 1;
                continue;
            }
            if (char === quote) quote = null;
            continue;
        }
        if (char === "/" && source[i + 1] === "/") {
            const newline = source.indexOf("\n", i);
            i = newline < 0 ? source.length : newline;
            continue;
        }
        if (char === '"' || char === "'" || char === "`") {
            quote = char;
            continue;
        }
        if (char === "{") depth += 1;
        if (char === "}") {
            depth -= 1;
            if (depth === 0) return source.slice(start, i + 1);
        }
    }
    throw new Error(`Unbalanced declaration ${name}`);
}

function bridgeSource() {
    const editor = fs.readFileSync(restrictionEditor, "utf8");
    const ids = fs.readFileSync(idsModule, "utf8");
    const needed = [
        "getApplicablePsets(schema, entityName.toUpperCase(), facet.predefinedType)",
        "getPredefinedTypes(schema, entityName.toUpperCase())",
        "getEntityAttributes(schema, entityName.toUpperCase())",
        "const ifcVersions = ['IFC4'];",
    ];
    for (const snippet of needed) {
        if (!editor.includes(snippet)) {
            throw new Error(`RestrictionEditor.svelte no longer contains: ${snippet}`);
        }
    }
    const closures = [
        ["getIfcVersions", "activeSpecification"],
        ["getEntityName", "facet"],
        ["getApplicabilityEntityNames", "activeSpecification"],
        ["getApplicabilityEntityFacets", "activeSpecification"],
    ];
    const wrapped = closures
        .map(([name, arg]) => {
            const declaration = extractDeclaration(editor, name);
            return `export function ${name}(${arg}) {\n${declaration}\nreturn ${name}();\n}`;
        })
        .join("\n");
    return `${extractDeclaration(ids, "normalizeIdsDict")}\n${wrapped}\nexport { normalizeIdsDict };\n`;
}

function bundleStamp() {
    return [restrictionEditor, idsModule, apiTs]
        .map((file) => {
            const stat = fs.statSync(file);
            return `${file}:${stat.mtimeMs}:${stat.size}`;
        })
        .join("|");
}

async function loadModules() {
    const dir = path.join(os.tmpdir(), "ifctester-injection-bundles");
    fs.mkdirSync(dir, { recursive: true });
    const bridgeOut = path.join(dir, "bridge.mjs");
    const apiOut = path.join(dir, "api.cjs");
    const stampFile = path.join(dir, "stamp");
    const stamp = bundleStamp();
    const cached = fs.existsSync(stampFile) && fs.readFileSync(stampFile, "utf8") === stamp;
    if (!cached) {
        await esbuild.build({
            stdin: {
                contents: bridgeSource(),
                resolveDir: path.dirname(restrictionEditor),
                sourcefile: "bridge.ts",
                loader: "ts",
            },
            bundle: true,
            format: "esm",
            platform: "node",
            outfile: bridgeOut,
        });
        // CJS so hyperid's require("crypto") keeps working. The bundle is the real worker api.ts.
        await esbuild.build({
            entryPoints: [apiTs],
            bundle: true,
            format: "cjs",
            platform: "node",
            outfile: apiOut,
        });
        fs.writeFileSync(stampFile, stamp);
    }
    const bridge = await import(`${pathToFileURL(bridgeOut).href}?stamp=${encodeURIComponent(stamp)}`);
    const api = require(apiOut);
    return { bridge, api };
}

function execPython(source, globals, marker) {
    const proc = spawnSync("python3", [evalScript], {
        input: JSON.stringify({ source, globals, marker }),
        encoding: "utf8",
    });
    if (proc.status !== 0) {
        throw new Error(proc.stderr || proc.stdout || "python eval helper failed");
    }
    return JSON.parse(proc.stdout);
}

function createPyodide(marker) {
    const calls = [];
    const globals = {};
    let sawInit = false;
    let markerWritten = false;
    const sources = [];

    function wrap(value) {
        return { toJs() { return value; } };
    }

    const apiModule = {
        get_predefined_types_for_entity(schema, entity) {
            calls.push({ fn: "get_predefined_types_for_entity", args: [schema, entity] });
            return wrap([]);
        },
        get_entity_attributes(schema, entity) {
            calls.push({ fn: "get_entity_attributes", args: [schema, entity] });
            return wrap([]);
        },
        get_applicable_psets(schema, entity, predefinedType = "") {
            calls.push({ fn: "get_applicable_psets", args: [schema, entity, predefinedType] });
            return wrap(["Pset_WallCommon"]);
        },
        get_all_entity_classes(schema) {
            calls.push({ fn: "get_all_entity_classes", args: [schema] });
            return wrap([]);
        },
        get_all_data_types(schema) {
            calls.push({ fn: "get_all_data_types", args: [schema] });
            return wrap({});
        },
    };

    const pyodide = {
        globals: {
            set(key, value) {
                globals[key] = value;
            },
            get(key) {
                return globals[key];
            },
        },
        pyimport(name) {
            if (name !== "api") throw new Error(`unexpected pyimport ${name}`);
            return apiModule;
        },
        async runPythonAsync(source) {
            if (!sawInit && source.includes("from pyodide.http import pyfetch")) {
                sawInit = true;
                return wrap(null);
            }
            sources.push(source);
            const result = execPython(source, globals, marker);
            calls.push(...result.calls);
            if (result.markerWritten) markerWritten = true;
            if (result.error) {
                const error = new Error(result.error);
                error.injected = true;
                throw error;
            }
            return wrap(result.value);
        },
    };

    return {
        pyodide,
        snapshot() {
            return { calls, markerWritten, sources };
        },
    };
}

async function main() {
    const documentPath = process.argv[2];
    const marker = process.argv[3];
    if (!documentPath || !marker) {
        throw new Error("usage: webapp_python_injection_runner.mjs <asdict.json> <marker>");
    }
    const selfCheck = spawnSync("python3", [evalScript, "--self-check"], { encoding: "utf8" });
    if (selfCheck.status !== 0) {
        throw new Error(selfCheck.stderr || "eval helper self-check failed");
    }

    const decoded = JSON.parse(fs.readFileSync(documentPath, "utf8"));
    const { bridge, api } = await loadModules();
    const document = bridge.normalizeIdsDict(decoded);
    const specification = document.specifications.specification[0];
    const session = createPyodide(marker);
    await api.init(session.pyodide);

    const errors = [];
    const returned = [];

    async function invoke(label, fn) {
        try {
            returned.push({ label, value: await fn() });
        } catch (error) {
            errors.push({ label, message: error instanceof Error ? error.message : String(error) });
        }
    }

    const entityFacets = specification.applicability?.entity;
    if (Array.isArray(entityFacets)) {
        for (const facet of entityFacets) {
            const entityName = bridge.getEntityName(facet);
            if (entityName && entityName.trim() !== "") {
                for (const schema of bridge.getIfcVersions(specification)) {
                    await invoke("getPredefinedTypes", () => api.getPredefinedTypes(schema, entityName.toUpperCase()));
                }
            }
        }
    }

    const attributeFacets = specification.applicability?.attribute;
    if (Array.isArray(attributeFacets) && attributeFacets.length > 0) {
        const entityNames = bridge.getApplicabilityEntityNames(specification);
        const schemas = bridge.getIfcVersions(specification);
        for (const entityName of entityNames) {
            for (const schema of schemas) {
                await invoke("getEntityAttributes", () =>
                    api.getEntityAttributes(schema, entityName.toUpperCase()),
                );
            }
        }
    }

    const propertyFacets = []
        .concat(specification.applicability?.property || [])
        .concat(specification.requirements?.property || []);
    if (propertyFacets.length > 0) {
        const facets = bridge.getApplicabilityEntityFacets(specification);
        for (const facet of facets) {
            for (const entityName of facet.entityNames) {
                await invoke("getApplicablePsets", () =>
                    api.getApplicablePsets("IFC4", entityName.toUpperCase(), facet.predefinedType),
                );
            }
        }
    }

    const snapshot = session.snapshot();
    process.stdout.write(
        JSON.stringify({
            calls: snapshot.calls,
            markerWritten: snapshot.markerWritten || fs.existsSync(marker),
            errors,
            returned,
            sources: snapshot.sources,
        }),
    );
}

main().catch((error) => {
    console.error(error);
    process.exit(1);
});
