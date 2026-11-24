// This file was generated with the assistance of an AI coding tool.
//
// Build a .ifcview whose element string table holds caller-supplied GlobalId,
// name, and type bytes, read that block back the way the web viewer does
// (compressed element-metadata frame -> SidecarCompress::decompress ->
// parseSidecarElementMetadata), and print the JSON array ifcv_request_objects_c
// would hand to Module.__ifcvOnObjectsBatch.
//
// appendJsonString is not in this file. The test runner compiles it in from
// src/ifcviewer-web/main_web.cpp so the encoder under test is the one the
// viewer ships.

#include "SidecarCache.h"
#include "SidecarCompress.h"
#include "StreamingLoader.h"

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

void appendJsonString(std::string& out, const char* data, std::uint32_t length);

namespace {

// Same bounds rule as ViewportCore::visitModelElements: an offset that runs
// past the table, or a zero length, means the sidecar wrote no string.
bool sliceTable(const std::string& table, std::uint32_t offset, std::uint32_t length,
                const char*& out_ptr, std::uint32_t& out_len) {
    if (length > 0 && std::size_t(offset) + length <= table.size()) {
        out_ptr = table.data() + offset;
        out_len = length;
        return true;
    }
    out_ptr = nullptr;
    out_len = 0;
    return false;
}

void appendElementJson(std::string& json, std::uint32_t object_id, int model_index, int source_id,
                       const char* guid, std::uint32_t guid_len,
                       const char* name, std::uint32_t name_len,
                       const char* type, std::uint32_t type_len) {
    // Field order matches ifcv_request_objects_c in main_web.cpp.
    json += "{\"objectId\":";
    json += std::to_string(object_id);
    json += ",\"model\":";
    json += std::to_string(model_index);
    json += ",\"sourceId\":";
    json += std::to_string(source_id);
    json += ",\"guid\":";
    appendJsonString(json, guid, guid_len);
    json += ",\"name\":";
    appendJsonString(json, name, name_len);
    json += ",\"type\":";
    appendJsonString(json, type, type_len);
    json += '}';
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 7) {
        std::cerr << "usage: emit_objects_json <dir> <model_index> <source_id> <guid> <name> <type>\n";
        return 1;
    }
    const std::string dir = argv[1];
    const int model_index = std::atoi(argv[2]);
    const int source_id = std::atoi(argv[3]);
    const std::string guid = argv[4];
    const std::string name = argv[5];
    const std::string type = argv[6];
    const std::uint32_t object_id = 42;

    SidecarData sd;
    sd.string_table.reserve(guid.size() + name.size() + type.size());
    ElementTableRecord packed{};
    packed.object_id = object_id;
    packed.session_model_id = 1;
    packed.ifc_id = 1000;
    packed.guid_offset = static_cast<std::uint32_t>(sd.string_table.size());
    packed.guid_length = static_cast<std::uint32_t>(guid.size());
    sd.string_table += guid;
    packed.name_offset = static_cast<std::uint32_t>(sd.string_table.size());
    packed.name_length = static_cast<std::uint32_t>(name.size());
    sd.string_table += name;
    packed.type_offset = static_cast<std::uint32_t>(sd.string_table.size());
    packed.type_length = static_cast<std::uint32_t>(type.size());
    sd.string_table += type;
    sd.elements.push_back(packed);

    const std::string ifc_path = dir + "/model.ifc";
    if (!writeSidecar(ifc_path, sd)) {
        std::cerr << "writeSidecar failed\n";
        return 2;
    }

    // Desktop read: decompresses both metadata blocks and parses the element
    // block with parseSidecarElementMetadata.
    const auto meta = readSidecarMetadata(ifc_path);
    if (!meta || meta->meta.elements.size() != 1) {
        std::cerr << "readSidecarMetadata failed\n";
        return 2;
    }

    // Web on-demand read: the bytes after the geometry metadata block are
    // [comp u64][raw u64][zstd]. Fetch that frame and parse it on its own,
    // which is what loadElementMetadataWeb does once it has the locator.
    const std::string ifcview = dir + "/model.ifcview";
    FILE* f = std::fopen(ifcview.c_str(), "rb");
    if (!f) {
        std::cerr << "open ifcview failed\n";
        return 2;
    }
    if (std::fseek(f, static_cast<long>(meta->element_metadata_comp_offset), SEEK_SET) != 0) {
        std::fclose(f);
        std::cerr << "seek element metadata failed\n";
        return 2;
    }
    std::vector<std::uint8_t> compressed(static_cast<std::size_t>(meta->element_metadata_comp_size));
    if (meta->element_metadata_comp_size > 0 &&
        std::fread(compressed.data(), 1, compressed.size(), f) != compressed.size()) {
        std::fclose(f);
        std::cerr << "read element metadata failed\n";
        return 2;
    }
    std::fclose(f);

    std::vector<std::uint8_t> raw(static_cast<std::size_t>(meta->element_metadata_raw_size));
    if (!SidecarCompress::decompress(compressed.data(), compressed.size(), raw.data(), raw.size())) {
        std::cerr << "decompress element metadata failed\n";
        return 2;
    }
    SidecarData parsed;
    if (!parseSidecarElementMetadata(raw.data(), raw.size(), parsed) || parsed.elements.size() != 1) {
        std::cerr << "parseSidecarElementMetadata failed\n";
        return 2;
    }
    if (parsed.string_table != meta->meta.string_table || parsed.string_table != sd.string_table) {
        std::cerr << "string table changed between write, desktop read, and web read\n";
        return 2;
    }

    const ElementTableRecord& e = parsed.elements[0];
    if (e.object_id != object_id) {
        std::cerr << "object id changed\n";
        return 2;
    }
    const char* guid_ptr = nullptr;
    const char* name_ptr = nullptr;
    const char* type_ptr = nullptr;
    std::uint32_t guid_len = 0, name_len = 0, type_len = 0;
    if (!sliceTable(parsed.string_table, e.guid_offset, e.guid_length, guid_ptr, guid_len) ||
        !sliceTable(parsed.string_table, e.name_offset, e.name_length, name_ptr, name_len) ||
        !sliceTable(parsed.string_table, e.type_offset, e.type_length, type_ptr, type_len)) {
        std::cerr << "string slice rejected an in-range element string\n";
        return 2;
    }
    if (std::string(guid_ptr, guid_len) != guid || std::string(name_ptr, name_len) != name ||
        std::string(type_ptr, type_len) != type) {
        std::cerr << "parsed element strings differ from the bytes written into the sidecar\n";
        return 2;
    }
    std::string json;
    json += '[';
    appendElementJson(json, e.object_id, model_index, source_id, guid_ptr, guid_len, name_ptr, name_len,
                      type_ptr, type_len);
    json += ']';
    std::cout << json;
    return 0;
}
