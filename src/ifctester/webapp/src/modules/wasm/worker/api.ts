import hyperid from 'hyperid';
import config from '../../../config.json';
import type { AuditReportData } from "$src/types/report";

let pyodide: any = null;
let api: any = null;
const id = hyperid();

const LoadedIFC = new Map<string, unknown>();

export async function init(pdide: any) {
    pyodide = pdide;

    // Load Python API bindings
    await pyodide.runPythonAsync(`
        from pyodide.http import pyfetch
        response = await pyfetch("${config.wasm.api_py_url}")
        with open("api.py", "wb") as f:
            f.write(await response.bytes())
    `);
    api = pyodide.pyimport("api");
}

// Values are passed to Python as call arguments, never interpolated into Python source.
export async function getPredefinedTypes(schema: string, entity: string) {
    const result = api.get_predefined_types_for_entity(schema, entity);
    return result.toJs({ dict_converter: Object.fromEntries });
}

export async function getAllEntityClasses(schema: string) {
    const result = api.get_all_entity_classes(schema);
    return result.toJs({ dict_converter: Object.fromEntries });
}

export async function getAllDataTypes(schema: string) {
    const result = api.get_all_data_types(schema);
    return result.toJs({ dict_converter: Object.fromEntries });
}

export async function getEntityAttributes(schema: string, entity: string) {
    const result = api.get_entity_attributes(schema, entity);
    return result.toJs({ dict_converter: Object.fromEntries });
}

export async function getApplicablePsets(schema: string, entity: string, predefinedType = '') {
    const result = api.get_applicable_psets(schema, entity, predefinedType);
    return result.toJs({ dict_converter: Object.fromEntries });
}

export async function getMaterialCategories() {
    const result = api.get_material_categories();
    return result.toJs({ dict_converter: Object.fromEntries });
}

export async function getStandardClassificationSystems() {
    const result = api.get_standard_classification_systems();
    return result.toJs({ dict_converter: Object.fromEntries });
}

export async function loadIfc(ifcData: number[] | Uint8Array | ArrayBuffer) {
    const ifc_id = id();
    const path = `/tmp/${encodeURIComponent(ifc_id)}.ifc`;

    pyodide.FS.writeFile(path, new Uint8Array(ifcData));
    const ifc = pyodide.pyimport("ifcopenshell").open(path);

    LoadedIFC.set(ifc_id, ifc);
    return ifc_id;
}

export async function unloadIfc(ifcId: string) {
    const path = `/tmp/${encodeURIComponent(ifcId)}.ifc`;

    pyodide.FS.unlink(path);
    LoadedIFC.delete(ifcId);
}

export async function auditIfc(ifcId: string, idsData: number[] | Uint8Array | ArrayBuffer) {
    const reporter = pyodide.pyimport("ifctester.reporter");

    const idsString = new TextDecoder().decode(new Uint8Array(idsData));
    const specs = api.ids_from_xml_string(idsString, true);
    const ifc = LoadedIFC.get(ifcId);

    // Run audit
    specs.validate(ifc);

    // Create report in both HTML and JSON formats
    const jsonReporter = reporter.Json(specs);
    jsonReporter.report();
    const jsonReport = jsonReporter.to_string();

    const htmlReporter = reporter.Html(specs);
    htmlReporter.report();
    const htmlReport = htmlReporter.to_string();

    return {
        json: JSON.parse(jsonReport) as AuditReportData,
        html: htmlReport
    };
}

// Expose interface
export const API = {
    "getPredefinedTypes": getPredefinedTypes,
    "getAllEntityClasses": getAllEntityClasses,
    "getAllDataTypes": getAllDataTypes,
    "getEntityAttributes": getEntityAttributes,
    "getApplicablePsets": getApplicablePsets,
    "getMaterialCategories": getMaterialCategories,
    "getStandardClassificationSystems": getStandardClassificationSystems,
    "loadIfc": loadIfc,
    "unloadIfc": unloadIfc,
    "auditIfc": auditIfc
};
