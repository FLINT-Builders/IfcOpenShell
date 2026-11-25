# This file was generated with the assistance of an AI coding tool.

"""Wavefront OBJ export must keep IFC text on a single statement.

Representation identifiers, context types, element names, GlobalIds, and
surface style names are written into OBJ group lines and into OBJ/MTL
material statements. Control characters in that text have to be removed
before the write. These tests fail while a newline or other control
character from the IFC file becomes another OBJ or MTL statement.

Run after building IfcConvert (the passthrough kernel is enough):

    IFCCONVERT=/path/to/IfcConvert IFCOS_BUILD_DIR=/path/to/build \\
        python3 src/serializers/tests/test_obj_representation_identifier_injection.py
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
IFCCONVERT = os.environ.get("IFCCONVERT", "")
BUILD_DIR = os.environ.get("IFCOS_BUILD_DIR", "")

GUID = "1s4VK6VcTBufQtdjWi3ZIK"
PROJECT = "0YvctVUKr0kugbFTf53O9L"
INJECTED_LIBRARY = "injected-library.mtl"
INJECTED_TEXTURE = "injected-texture.png"

# tinyobjloader v2.0.0rc13 safeGetline() ends a statement on CR or LF.
# IS_SPACE() treats space and tab as the gap between a keyword and its argument.


def statement_lines(data: bytes):
    lines = []
    buf = bytearray()
    i = 0
    while i < len(data):
        c = data[i]
        if c == 10:
            lines.append(buf.decode("latin1"))
            buf.clear()
            i += 1
        elif c == 13:
            lines.append(buf.decode("latin1"))
            buf.clear()
            i += 1
            if i < len(data) and data[i] == 10:
                i += 1
        else:
            buf.append(c)
            i += 1
    if buf:
        lines.append(buf.decode("latin1"))
    return [line for line in lines if line.strip(" \t") != ""]


def keyword_argument(line, keyword):
    token = line.lstrip(" \t")
    if len(token) <= len(keyword) or not token.startswith(keyword):
        return None
    if token[len(keyword)] not in " \t":
        return None
    return token[len(keyword) + 1 :]


def assert_no_control_characters(testcase, data):
    for line in statement_lines(data):
        controls = [ch for ch in line if ord(ch) < 32]
        testcase.assertEqual(controls, [], "control character survived in %r" % line)


def assert_obj_has_only_its_own_library(testcase, obj, mtl_basename):
    libraries = []
    for line in statement_lines(obj):
        argument = keyword_argument(line, "mtllib")
        if argument is not None:
            libraries.append(argument.split(" ")[0])
        testcase.assertIsNone(keyword_argument(line, "map_Kd"))
    testcase.assertEqual(libraries, [mtl_basename])


def assert_mtl_has_no_texture_statement(testcase, mtl):
    for line in statement_lines(mtl):
        testcase.assertIsNone(keyword_argument(line, "map_Kd"))


def assert_export_is_inert(testcase, obj_path):
    obj = obj_path.read_bytes()
    mtl_path = obj_path.with_suffix(".mtl")
    mtl = mtl_path.read_bytes()
    testcase.assertTrue(any(line.startswith("v ") or line.startswith("l ") for line in statement_lines(obj)))
    assert_no_control_characters(testcase, obj)
    assert_no_control_characters(testcase, mtl)
    assert_obj_has_only_its_own_library(testcase, obj, mtl_path.name)
    assert_mtl_has_no_texture_statement(testcase, mtl)


def ifc_document(identifier, element_name, guid, context_type="Model", style_name=None):
    identifier_token = "$" if identifier is None else "'%s'" % identifier
    style = ""
    if style_name is not None:
        style = """
#21=IFCCOLOURRGB($,0.8,0.2,0.1);
#22=IFCSURFACESTYLESHADING(#21,0.);
#23=IFCSURFACESTYLE('%s',.BOTH.,(#22));
#24=IFCSTYLEDITEM(#15,(#23),$);
""" % style_name
    return """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('inject.ifc','2020-01-01T00:00:00',(''),(''),'','','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
#2=IFCUNITASSIGNMENT((#1));
#3=IFCCARTESIANPOINT((0.,0.,0.));
#4=IFCDIRECTION((0.,0.,1.));
#5=IFCDIRECTION((1.,0.,0.));
#6=IFCAXIS2PLACEMENT3D(#3,#4,#5);
#7=IFCGEOMETRICREPRESENTATIONCONTEXT($,'%s',3,1.E-05,#6,$);
#8=IFCCARTESIANPOINT((0.,0.));
#9=IFCDIRECTION((1.,0.));
#10=IFCAXIS2PLACEMENT2D(#8,#9);
#11=IFCRECTANGLEPROFILEDEF(.AREA.,$,#10,1.,1.);
#12=IFCCARTESIANPOINT((0.,0.,0.));
#13=IFCAXIS2PLACEMENT3D(#12,#4,#5);
#14=IFCDIRECTION((0.,0.,1.));
#15=IFCEXTRUDEDAREASOLID(#11,#13,#14,1.);
#16=IFCSHAPEREPRESENTATION(#7,%s,'SweptSolid',(#15));
#17=IFCPRODUCTDEFINITIONSHAPE($,$,(#16));
#18=IFCLOCALPLACEMENT($,#6);
#19=IFCBUILDINGELEMENTPROXY('%s',$,'%s',$,$,#18,#17,$,$);
#20=IFCPROJECT('%s',$,'Project',$,$,$,$,(#7),#2);
%s
ENDSEC;
END-ISO-10303-21;
""" % (context_type, identifier_token, guid, element_name, PROJECT, style)


class ObjInjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not IFCCONVERT or not Path(IFCCONVERT).is_file():
            raise RuntimeError("Set IFCCONVERT to the IfcConvert binary built from this commit")
        if not BUILD_DIR:
            raise RuntimeError("Set IFCOS_BUILD_DIR to the build directory that produced IfcConvert")

    def convert(self, document, extra_args=()):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        ifc_path = root / "input.ifc"
        obj_path = root / "output.obj"
        ifc_path.write_text(document)
        completed = subprocess.run(
            [IFCCONVERT, "--kernel", "passthrough", *extra_args, str(ifc_path), str(obj_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(obj_path.is_file())
        return obj_path

    def test_benign_body_identifier_stays_one_statement(self):
        obj = self.convert(ifc_document("Body", "Proxy", GUID))
        assert_export_is_inert(self, obj)
        group_lines = [line for line in statement_lines(obj.read_bytes()) if line.startswith("g ")]
        self.assertEqual(len(group_lines), 1)
        self.assertTrue(group_lines[0].endswith("-body"))

    def test_representation_identifier_newline_and_tab_do_not_add_mtllib(self):
        # Default object id. A space would be rewritten to a dash, so the
        # directive is separated with a tab, which the id builder leaves intact.
        identifier = r"Body\X\0Amtllib\X\09" + INJECTED_LIBRARY
        obj = self.convert(ifc_document(identifier, "Proxy", GUID))
        assert_export_is_inert(self, obj)

    def test_representation_identifier_carriage_return_does_not_add_mtllib(self):
        identifier = r"Body\X\0Dmtllib\X\09" + INJECTED_LIBRARY
        obj = self.convert(ifc_document(identifier, "Proxy", GUID))
        assert_export_is_inert(self, obj)

    def test_representation_identifier_crlf_does_not_add_mtllib(self):
        identifier = r"Body\X\0D\X\0Amtllib\X\09" + INJECTED_LIBRARY
        obj = self.convert(ifc_document(identifier, "Proxy", GUID))
        assert_export_is_inert(self, obj)

    def test_literal_newline_in_representation_identifier_does_not_add_mtllib(self):
        identifier = "Body\nmtllib\t" + INJECTED_LIBRARY
        obj = self.convert(ifc_document(identifier, "Proxy", GUID))
        assert_export_is_inert(self, obj)

    def test_other_control_character_is_not_copied_into_the_group_name(self):
        identifier = r"Body\X\01tail"
        obj = self.convert(ifc_document(identifier, "Proxy", GUID))
        assert_export_is_inert(self, obj)

    def test_missing_identifier_uses_context_type_without_adding_mtllib(self):
        context = r"Model\X\0Amtllib\X\09" + INJECTED_LIBRARY
        obj = self.convert(ifc_document(None, "Proxy", GUID, context_type=context))
        assert_export_is_inert(self, obj)

    def test_element_name_option_does_not_add_mtllib(self):
        # Names are written as the group id without the space-to-dash rewrite.
        name = r"Wall\X\0Amtllib " + INJECTED_LIBRARY
        obj = self.convert(ifc_document("Body", name, GUID), extra_args=("--use-element-names",))
        assert_export_is_inert(self, obj)

    def test_element_guid_option_does_not_add_mtllib(self):
        guid = r"1s4VK6VcTBufQtdjWi3Z\X\0Amtllib " + INJECTED_LIBRARY
        obj = self.convert(ifc_document("Body", "Proxy", guid), extra_args=("--use-element-guids",))
        assert_export_is_inert(self, obj)

    def test_surface_style_name_does_not_add_a_texture_statement(self):
        style = r"Red\X\0Amap_Kd\X\09" + INJECTED_TEXTURE
        obj = self.convert(
            ifc_document("Body", "Proxy", GUID, style_name=style),
            extra_args=("--use-material-names",),
        )
        assert_export_is_inert(self, obj)

    def test_edge_loop_does_not_write_a_texture_statement(self):
        style = r"Red\X\0Amap_Kd\X\09" + INJECTED_TEXTURE
        document = ifc_document("Body", "Proxy", GUID, style_name=style)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        ifc_path = root / "input.ifc"
        obj_path = root / "output.obj"
        mtl_path = root / "output.mtl"
        ifc_path.write_text(document)
        binary = compile_edge_driver(root)
        completed = subprocess.run(
            [str(binary), str(ifc_path), str(obj_path), str(mtl_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        obj = obj_path.read_bytes()
        self.assertTrue(any(line.startswith("l ") for line in statement_lines(obj)))
        assert_export_is_inert(self, obj_path)


def compile_edge_driver(root: Path) -> Path:
    source = Path(__file__).with_name("test_obj_edge_material_line.cpp")
    binary = root / "test_obj_edge_material_line"
    build = Path(BUILD_DIR)
    command = [
        "g++",
        "-std=c++17",
        str(source),
        "-I%s" % (REPO / "src" / "serializers"),
        "-I%s" % (REPO / "src"),
        "-isystem",
        "/usr/include/eigen3",
        "-L%s" % (build / "ifcgeom"),
        "-L%s" % (build / "ifcparse"),
        "-L%s" % (build / "plugin"),
        "-Wl,-rpath,%s:%s:%s" % (build / "ifcgeom", build / "ifcparse", build / "plugin"),
        str(build / "ifcgeom" / "ifcopenshell_geometry_obj.so"),
        "-lifcopenshell.geometry",
        "-lifcopenshell.parse",
        "-lifcopenshell.plugin",
        "-o",
        str(binary),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError("edge driver did not compile:\n" + completed.stderr)
    return binary


if __name__ == "__main__":
    unittest.main()
