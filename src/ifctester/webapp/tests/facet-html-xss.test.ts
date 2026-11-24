// This file was generated with the assistance of an AI coding tool.
/**
 * IDS facet values must not become live HTML in the viewer or the editor.
 *
 * These tests fail while facet sentences are inserted with `{@html}` without
 * escaping values supplied by an IDS file. They pass once those values are
 * escaped (or rendered as text).
 *
 * Not covered:
 * - partOf @relation is an ids:relations enumeration, so a schema-valid file
 *   cannot put markup in it.
 * - partOf entity name and predefinedType are nested under `entity` by
 *   PartOf.asdict, while stringifyFacet reads `facet.name`. The viewer and
 *   editor do not insert those strings.
 * - xs:length, xs:minLength, and xs:maxLength are xs:nonNegativeInteger, so
 *   markup does not survive schema validation.
 * Document title, description, instructions, and specification name are
 * rendered with Svelte text bindings, not `{@html}`.
 */
import { render } from "@testing-library/svelte";
import { tick } from "svelte";
import { beforeAll, describe, expect, it, vi } from "vitest";

const chromePath = process.env.CHROME_PATH ?? "/usr/local/bin/google-chrome";

window.matchMedia = (query: string) =>
    ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => undefined,
        removeListener: () => undefined,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        dispatchEvent: () => false,
    }) as MediaQueryList;

const { openIdsThroughPython } = vi.hoisted(() => ({
    openIdsThroughPython: (xml: string) =>
        new Promise<Record<string, unknown>>((resolve, reject) => {
            void (async () => {
                const { spawn } = await import("node:child_process");
                const path = await import("node:path");
                const { fileURLToPath } = await import("node:url");
                const here = path.dirname(fileURLToPath(import.meta.url));
                const repoRoot = path.resolve(here, "../../../..");
                const child = spawn("python3", [path.join(here, "open_ids.py")], {
                    env: {
                        ...process.env,
                        PYTHONPATH: [
                            path.join(repoRoot, "src/ifctester"),
                            path.join(repoRoot, "src/ifctester/webapp/public/worker"),
                            process.env.PYTHONPATH ?? "",
                        ].join(path.delimiter),
                    },
                });
                let stdout = "";
                let stderr = "";
                child.stdout.setEncoding("utf8");
                child.stderr.setEncoding("utf8");
                child.stdout.on("data", (chunk) => {
                    stdout += chunk;
                });
                child.stderr.on("data", (chunk) => {
                    stderr += chunk;
                });
                child.on("error", reject);
                child.on("close", (code) => {
                    if (code !== 0) {
                        reject(new Error(`ids_from_xml_string failed (${code}): ${stderr}`));
                        return;
                    }
                    resolve(JSON.parse(stdout) as Record<string, unknown>);
                });
                child.stdin.end(xml);
            })().catch(reject);
        }),
}));

vi.mock("$src/modules/wasm", () => ({
    default: {
        init: () => Promise.resolve(),
        // Pyodide's toJs copies Python str code points and does not escape HTML.
        // JSON preserves the same characters for these ASCII facet values.
        openIDS: (xml: string) => openIdsThroughPython(xml),
        createIDS: () => Promise.resolve({}),
        exportIDS: () => Promise.resolve(""),
        getAllEntityClasses: () => Promise.resolve([]),
        getAllDataTypes: () => Promise.resolve({}),
        getMaterialCategories: () => Promise.resolve([]),
        getStandardClassificationSystems: () => Promise.resolve({}),
        getPredefinedTypes: () => Promise.resolve([]),
        getEntityAttributes: () => Promise.resolve([]),
        getApplicablePsets: () => Promise.resolve([]),
    },
}));

import * as IDS from "$src/modules/api/ids.svelte";
import ApplicabilityPanel from "$src/pages/Home/ApplicabilityPanel.svelte";
import IdsViewer from "$src/pages/Home/IdsViewer.svelte";
import RequirementsPanel from "$src/pages/Home/RequirementsPanel.svelte";

const MARKER = "data-executed";

function facetPayload(id: string, numericEntities = false): string {
    const tag = `<img src=x id="${id}" onerror="this.setAttribute('${MARKER}','1')">`;
    if (numericEntities) {
        return tag
            .replaceAll("<", "&#60;")
            .replaceAll(">", "&#62;")
            .replaceAll('"', "&#34;");
    }
    return tag
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
}

const RENDERED_IDS = [
    "xss-app-entity-name",
    "xss-app-entity-type",
    "xss-app-class-value",
    "xss-app-class-system",
    "xss-app-attr-name",
    "xss-app-attr-value",
    "xss-app-prop-set",
    "xss-app-prop-base",
    "xss-app-prop-value",
    "xss-app-material",
    "xss-req-entity-name",
    "xss-req-entity-type",
    "xss-req-class-value",
    "xss-req-class-system",
    "xss-req-attr-name",
    "xss-req-attr-value",
    "xss-req-prop-set",
    "xss-req-prop-base",
    "xss-req-prop-value",
    "xss-req-material",
    "xss-enum",
    "xss-pattern",
    "xss-min-inc",
    "xss-max-inc",
    "xss-min-exc",
    "xss-max-exc",
] as const;

function craftedIds(): string {
    const value = (id: string, numeric = false) =>
        `<simpleValue>${facetPayload(id, numeric)}</simpleValue>`;
    const restriction = (body: string) =>
        `<xs:restriction base="xs:string">${body}</xs:restriction>`;
    return `<?xml version="1.0" encoding="UTF-8"?>
<ids xmlns="http://standards.buildingsmart.org/IDS"
     xmlns:xs="http://www.w3.org/2001/XMLSchema"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xsi:schemaLocation="http://standards.buildingsmart.org/IDS http://standards.buildingsmart.org/IDS/1.0/ids.xsd">
  <info><title>Requirements</title></info>
  <specifications>
    <specification name="Crafted specification" ifcVersion="IFC4">
      <applicability minOccurs="1" maxOccurs="unbounded">
        <entity>
          <name>${value("xss-app-entity-name")}</name>
          <predefinedType>${value("xss-app-entity-type")}</predefinedType>
        </entity>
        <partOf relation="IFCRELAGGREGATES">
          <entity>
            <name>${value("xss-app-partof-name")}</name>
            <predefinedType>${value("xss-app-partof-type")}</predefinedType>
          </entity>
        </partOf>
        <classification>
          <value>${value("xss-app-class-value")}</value>
          <system>${value("xss-app-class-system")}</system>
        </classification>
        <attribute>
          <name>${value("xss-app-attr-name")}</name>
          <value>${value("xss-app-attr-value")}</value>
        </attribute>
        <property>
          <propertySet>${value("xss-app-prop-set")}</propertySet>
          <baseName>${value("xss-app-prop-base")}</baseName>
          <value>${value("xss-app-prop-value")}</value>
        </property>
        <material>
          <value>${value("xss-app-material")}</value>
        </material>
      </applicability>
      <requirements>
        <entity>
          <name>${value("xss-req-entity-name", true)}</name>
          <predefinedType>${value("xss-req-entity-type")}</predefinedType>
        </entity>
        <partOf relation="IFCRELNESTS">
          <entity><name>${value("xss-req-partof-name")}</name></entity>
        </partOf>
        <classification>
          <value>${value("xss-req-class-value")}</value>
          <system>${value("xss-req-class-system")}</system>
        </classification>
        <attribute>
          <name>${value("xss-req-attr-name")}</name>
          <value>${value("xss-req-attr-value")}</value>
        </attribute>
        <attribute>
          <name><simpleValue>Name</simpleValue></name>
          <value>${restriction(`<xs:enumeration value="${facetPayload("xss-enum")}"/>`)}</value>
        </attribute>
        <attribute>
          <name><simpleValue>Description</simpleValue></name>
          <value>${restriction(`<xs:pattern value="${facetPayload("xss-pattern")}"/>`)}</value>
        </attribute>
        <attribute>
          <name><simpleValue>Tag</simpleValue></name>
          <value>${restriction(
              [
                  "xss-min-inc",
                  "xss-max-inc",
                  "xss-min-exc",
                  "xss-max-exc",
              ]
                  .map((id, index) => {
                      const facet = ["minInclusive", "maxInclusive", "minExclusive", "maxExclusive"][index];
                      return `<xs:${facet} value="${facetPayload(id)}"/>`;
                  })
                  .join(""),
          )}</value>
        </attribute>
        <property>
          <propertySet>${value("xss-req-prop-set")}</propertySet>
          <baseName>${value("xss-req-prop-base")}</baseName>
          <value>${value("xss-req-prop-value")}</value>
        </property>
        <material>
          <value>${value("xss-req-material")}</value>
        </material>
      </requirements>
    </specification>
  </specifications>
</ids>`;
}

async function openCraftedDocument(): Promise<void> {
    const xml = craftedIds();
    const realCreate = document.createElement.bind(document);
    const spy = vi.spyOn(document, "createElement").mockImplementation((
        tag: string,
        options?: ElementCreationOptions,
    ) => {
        const element = realCreate(tag, options) as HTMLInputElement;
        if (tag.toLowerCase() === "input") {
            setTimeout(() => {
                const file = new File([xml], "requirements.ids", { type: "text/xml" });
                Object.defineProperty(element, "files", { value: [file] });
                element.dispatchEvent(new Event("change"));
            }, 0);
        }
        return element;
    });
    try {
        await IDS.openDocument();
    } finally {
        spy.mockRestore();
    }
}

function markupFrom(selector: string): string[] {
    return [...document.querySelectorAll(selector)].map((node) => (node as HTMLElement).innerHTML);
}

async function chromeExecutes(html: string): Promise<boolean> {
    const { spawn } = await import("node:child_process");
    const path = await import("node:path");
    const { fileURLToPath } = await import("node:url");
    const script = path.join(path.dirname(fileURLToPath(import.meta.url)), "chrome_innerhtml.mjs");
    return await new Promise((resolve, reject) => {
        const child = spawn(process.execPath, [script], {
            env: { ...process.env, CHROME_PATH: chromePath, XSS_MARKER: MARKER },
        });
        let stdout = "";
        let stderr = "";
        child.stdout.setEncoding("utf8");
        child.stderr.setEncoding("utf8");
        child.stdout.on("data", (chunk) => {
            stdout += chunk;
        });
        child.stderr.on("data", (chunk) => {
            stderr += chunk;
        });
        child.on("error", reject);
        child.on("close", (code) => {
            if (code !== 0) {
                reject(new Error(`chrome innerHTML check failed (${code}): ${stderr}`));
                return;
            }
            resolve(stdout.trim() === "true");
        });
        child.stdin.end(html);
    });
}

describe("IDS facet HTML", () => {
    beforeAll(async () => {
        await openCraftedDocument();
        const docId = IDS.Module.activeDocument;
        if (!docId) throw new Error("openDocument did not store the IDS file");
        IDS.setDocumentState(docId, { activeSpecification: 0, activeTab: "applicability" });
    });

    it("does not run markup from an opened IDS file in the viewer or the editor", async () => {
        const viewer = render(IdsViewer);
        const header = viewer.container.querySelector(".spec-card-header");
        if (!header) throw new Error("specification header was not rendered");
        header.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        await tick();

        const applicability = render(ApplicabilityPanel);
        IDS.setDocumentState(IDS.Module.activeDocument as string, { activeTab: "requirements" });
        await tick();
        const requirements = render(RequirementsPanel);
        await tick();

        const viewerHtml = markupFrom(".facet-text");
        const editorHtml = [
            ...applicability.container.querySelectorAll(".restriction-name"),
            ...requirements.container.querySelectorAll(".restriction-name"),
        ].map((node) => (node as HTMLElement).innerHTML);
        const rendered = [...viewerHtml, ...editorHtml].join("\n");

        for (const id of RENDERED_IDS) {
            expect(rendered, `facet value ${id} was not shown`).toContain(id);
        }

        const executed = await chromeExecutes(rendered);
        expect(executed).toBe(false);

        for (const html of [...viewerHtml, ...editorHtml]) {
            const probe = document.createElement("div");
            probe.innerHTML = html;
            expect([...probe.querySelectorAll("img")].map((img) => img.id)).toEqual([]);
            const handlers = [...probe.querySelectorAll("*")].flatMap((element) =>
                [...element.attributes]
                    .filter((attribute) => attribute.name.startsWith("on"))
                    .map((attribute) => attribute.name),
            );
            expect(handlers).toEqual([]);
        }
    });
});
