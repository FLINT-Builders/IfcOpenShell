// This file was generated with the assistance of an AI coding tool.

// Typed values in a streaming header are resolved before any schema or owning
// file exists. These tests are the expected behaviour once that lookup no
// longer dereferences a null file: the process must keep running, the header
// schema must still be applied, and the DATA section must still be readable.
// They fail while in_memory_file_storage looks the type up through a null
// owner. Each case runs in a child with default fatal-signal disposition so a
// SIGSEGV is reported as a failed assertion instead of aborting the suite.

#include <catch2/catch_test_macros.hpp>
#include <cerrno>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <ifcparse/file.h>
#include <stdexcept>
#include <string>
#include <string_view>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>

namespace {

enum class Entry {
    Buffer,
    Path,
    Page,
    OwningFile,
};

enum class Shape {
    PlainHeader,
    TypedInList,
    TypedAttribute,
    TypedInData,
};

const char* shape_name(Shape shape) {
    switch (shape) {
    case Shape::PlainHeader:
        return "plain header";
    case Shape::TypedInList:
        return "typed value inside a header list";
    case Shape::TypedAttribute:
        return "typed value as a header attribute";
    case Shape::TypedInData:
        return "typed value in DATA after the schema is known";
    }
    return "unknown";
}

std::string file_description(Shape shape) {
    if (shape == Shape::TypedInList) {
        return "(IFCLABEL('x')),'2;1'";
    }
    if (shape == Shape::TypedAttribute) {
        return "('ViewDefinition [CoordinationView]'),IFCLABEL('x')";
    }
    return "('ViewDefinition [CoordinationView]'),'2;1'";
}

std::string data_section(Shape shape) {
    if (shape == Shape::TypedInData) {
        return "#1=IFCPROPERTYSINGLEVALUE('Name',$,IFCLABEL('x'),$);\n";
    }
    return "#1=IFCCARTESIANPOINT((0.,0.,0.));\n";
}

std::string spf(Shape shape) {
    return std::string("ISO-10303-21;\n"
                       "HEADER;\n"
                       "FILE_DESCRIPTION(") +
           file_description(shape) +
           ");\n"
           "FILE_NAME('test','2020-01-01T00:00:00',('a'),('o'),'p','os','a');\n"
           "FILE_SCHEMA(('IFC4'));\n"
           "ENDSEC;\n"
           "DATA;\n" +
           data_section(shape) +
           "ENDSEC;\n"
           "END-ISO-10303-21;\n";
}

int fail(int code, const char* why) {
    std::fprintf(stderr, "%s\n", why);
    return code;
}

bool saw_instance(ifcopenshell::instance_streamer<>& streamer, std::string_view type_name) {
    while (streamer) {
        auto instance = streamer.read_instance();
        if (!instance) {
            break;
        }
        const auto* declaration = std::get<1>(*instance);
        if (std::get<0>(*instance) == 1 && declaration != nullptr && declaration->name() == type_name) {
            if (type_name != "IfcPropertySingleValue") {
                return true;
            }
            express::base value(std::get<2>(*instance));
            const express::base nominal = value.get_attribute_value(2);
            if (!nominal || nominal.declaration().name() != "IfcLabel") {
                return false;
            }
            return true;
        }
    }
    return false;
}

int read_streamer(ifcopenshell::instance_streamer<>& streamer, Shape shape) {
    if (!streamer.status()) {
        return fail(2, "streaming parser did not accept the file");
    }
    const auto* schema = streamer.schema();
    if (schema == nullptr || schema->name() != "IFC4") {
        return fail(3, "streaming parser did not resolve the IFC4 schema");
    }
    const char* expected = shape == Shape::TypedInData ? "IfcPropertySingleValue" : "IfcCartesianPoint";
    if (!saw_instance(streamer, expected)) {
        return fail(4, "streaming parser did not yield the DATA instance");
    }
    return 0;
}

int exercise(Entry entry, Shape shape, const std::string& path) {
    const std::string contents = spf(shape);
    try {
        if (entry == Entry::Buffer) {
            ifcopenshell::instance_streamer<> streamer(const_cast<char*>(contents.data()), static_cast<int>(contents.size()));
            return read_streamer(streamer, shape);
        }
        if (entry == Entry::Path) {
            ifcopenshell::instance_streamer<> streamer(path);
            return read_streamer(streamer, shape);
        }
        if (entry == Entry::Page) {
            ifcopenshell::instance_streamer<> streamer;
            streamer.push_page(contents);
            return read_streamer(streamer, shape);
        }

        ifcopenshell::file file(const_cast<char*>(contents.data()), static_cast<int>(contents.size()));
        if (!file.good()) {
            return fail(2, "owning file parser did not accept the file");
        }
        if (file.schema() == nullptr || file.schema()->name() != "IFC4") {
            return fail(3, "owning file parser did not resolve the IFC4 schema");
        }
        const char* expected = shape == Shape::TypedInData ? "IfcPropertySingleValue" : "IfcCartesianPoint";
        const auto instances = file.instances_by_type(expected);
        if (instances.size() != 1) {
            return fail(4, "owning file parser did not keep the DATA instance");
        }
        if (shape == Shape::TypedInData) {
            const express::base nominal = instances.front().get_attribute_value(2);
            if (!nominal || nominal.declaration().name() != "IfcLabel") {
                return fail(4, "owning file parser dropped the typed DATA value");
            }
        }
        return 0;
    } catch (const std::exception& ex) {
        std::fprintf(stderr, "exception: %s\n", ex.what());
        return fail(5, "parser threw instead of skipping the typed header value");
    }
}

std::string write_temp(const std::string& contents) {
    char templ[] = "/tmp/ifc-typed-header-XXXXXX";
    const int descriptor = mkstemp(templ);
    if (descriptor < 0) {
        throw std::runtime_error(std::string("mkstemp failed: ") + std::strerror(errno));
    }
    const std::string path(templ);
    {
        std::ofstream output(path, std::ios::binary);
        output << contents;
        if (!output) {
            close(descriptor);
            unlink(path.c_str());
            throw std::runtime_error("failed to write temporary IFC");
        }
    }
    close(descriptor);
    return path;
}

void require_clean_exit(Entry entry, Shape shape) {
    std::string path;
    if (entry == Entry::Path) {
        path = write_temp(spf(shape));
    }

    const pid_t child = fork();
    if (child < 0) {
        if (!path.empty()) {
            unlink(path.c_str());
        }
        FAIL("fork failed: " << std::strerror(errno));
    }
    if (child == 0) {
        std::signal(SIGSEGV, SIG_DFL);
        std::signal(SIGBUS, SIG_DFL);
        std::signal(SIGABRT, SIG_DFL);
        const int code = exercise(entry, shape, path);
        _exit(code);
    }

    int status = 0;
    const pid_t waited = waitpid(child, &status, 0);
    if (!path.empty()) {
        unlink(path.c_str());
    }
    REQUIRE(waited == child);
    INFO(shape_name(shape));
    if (WIFSIGNALED(status)) {
        FAIL("parser aborted with signal " << WTERMSIG(status));
    }
    REQUIRE(WIFEXITED(status));
    REQUIRE(WEXITSTATUS(status) == 0);
}

} // namespace

TEST_CASE("A plain header streams without an owning file", "[ifcparse][streaming-header]") {
    SECTION("buffer constructor") {
        require_clean_exit(Entry::Buffer, Shape::PlainHeader);
    }
    SECTION("path constructor") {
        require_clean_exit(Entry::Path, Shape::PlainHeader);
    }
    SECTION("caller-fed page") {
        require_clean_exit(Entry::Page, Shape::PlainHeader);
    }
}

TEST_CASE("A typed value inside a header list does not crash the streaming parser", "[ifcparse][streaming-header]") {
    // FILE_DESCRIPTION((IFCLABEL('x')),'2;1') reaches read_direct_aggregate
    // while storage.schema and storage.file are both null.
    SECTION("buffer constructor") {
        require_clean_exit(Entry::Buffer, Shape::TypedInList);
    }
    SECTION("path constructor") {
        require_clean_exit(Entry::Path, Shape::TypedInList);
    }
    SECTION("caller-fed page") {
        require_clean_exit(Entry::Page, Shape::TypedInList);
    }
}

TEST_CASE("A typed header attribute does not crash the streaming parser", "[ifcparse][streaming-header]") {
    // FILE_DESCRIPTION(('...'),IFCLABEL('x')) reaches in_memory_file_storage::load
    // while storage.schema and storage.file are both null.
    SECTION("buffer constructor") {
        require_clean_exit(Entry::Buffer, Shape::TypedAttribute);
    }
    SECTION("path constructor") {
        require_clean_exit(Entry::Path, Shape::TypedAttribute);
    }
    SECTION("caller-fed page") {
        require_clean_exit(Entry::Page, Shape::TypedAttribute);
    }
}

TEST_CASE("A typed DATA value still resolves once the schema is known", "[ifcparse][streaming-header]") {
    SECTION("buffer constructor") {
        require_clean_exit(Entry::Buffer, Shape::TypedInData);
    }
    SECTION("path constructor") {
        require_clean_exit(Entry::Path, Shape::TypedInData);
    }
    SECTION("caller-fed page") {
        require_clean_exit(Entry::Page, Shape::TypedInData);
    }
    SECTION("owning file") {
        require_clean_exit(Entry::OwningFile, Shape::TypedInData);
    }
}

TEST_CASE("An owning file parser accepts a typed header value", "[ifcparse][streaming-header]") {
    SECTION("typed value inside a header list") {
        require_clean_exit(Entry::OwningFile, Shape::TypedInList);
    }
    SECTION("typed value as a header attribute") {
        require_clean_exit(Entry::OwningFile, Shape::TypedAttribute);
    }
    SECTION("plain header") {
        require_clean_exit(Entry::OwningFile, Shape::PlainHeader);
    }
}
