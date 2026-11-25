# This file was generated with the assistance of an AI coding tool.

"""IfcConvert XML export must finish on cyclic IfcGroup membership.

writeGroupToNode walks IfcRelAssignsToGroup. The notRootGroups set is passed
by value and a child name is recorded only after the recursive call, so a
cycle never hits the guard. These tests run IfcConvert itself. They fail
while that walk can recurse without a bound, and they pass once every group
is emitted once, nested groups stay nested, and a repeated entity is skipped.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


IFCCONVERT = os.environ.get("IFCCONVERT", "IfcConvert")
CONVERT_TIMEOUT_SECONDS = 20
MAX_XML_BYTES = 256 * 1024


def _guid(n):
    # 22 characters from the IFC GlobalId alphabet. The parser stores the
    # string as given; the XML writer emits it as the id attribute.
    return f"{n:022d}"


def _project():
    return "\n".join(
        [
            "#1=IFCPROJECT('%s',$,'Project',$,$,$,$,$,#2);" % _guid(1),
            "#2=IFCUNITASSIGNMENT((#3));",
            "#3=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);",
        ]
    )


def _ifc(body):
    return "\n".join(
        [
            "ISO-10303-21;",
            "HEADER;",
            "FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');",
            "FILE_NAME('groups.ifc','2026-01-01T00:00:00',(''),(''),'test','test','');",
            "FILE_SCHEMA(('IFC4'));",
            "ENDSEC;",
            "DATA;",
            _project(),
            body.rstrip(),
            "ENDSEC;",
            "END-ISO-10303-21;",
            "",
        ]
    )


def _group(step_id, guid_n, name, entity="IFCGROUP"):
    return "#%d=%s('%s',$,'%s',$,$);" % (step_id, entity, _guid(guid_n), name.replace("'", "''"))


def _assign(step_id, guid_n, child_ids, parent_id):
    children = ",".join("#%d" % i for i in child_ids)
    return "#%d=IFCRELASSIGNSTOGROUP('%s',$,$,$,(%s),$,#%d);" % (step_id, _guid(guid_n), children, parent_id)


def _convert(ifc_text):
    if shutil.which(IFCCONVERT) is None and not Path(IFCCONVERT).is_file():
        raise AssertionError("IfcConvert not found: set IFCCONVERT to the built binary")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "groups.ifc"
        dst = Path(tmp) / "groups.xml"
        src.write_text(ifc_text, encoding="utf-8")
        try:
            proc = subprocess.run(
                [IFCCONVERT, str(src), str(dst)],
                capture_output=True,
                text=True,
                timeout=CONVERT_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AssertionError(
                "IfcConvert did not finish within %ss; XML group walk is unbounded"
                % CONVERT_TIMEOUT_SECONDS
            ) from exc
        temp = Path(str(dst) + ".tmp")
        if proc.returncode != 0:
            raise AssertionError(
                "IfcConvert exited %s\nstdout:\n%s\nstderr:\n%s"
                % (proc.returncode, proc.stdout, proc.stderr)
            )
        if not dst.is_file():
            raise AssertionError("IfcConvert exited 0 without writing %s" % dst)
        if temp.exists():
            raise AssertionError("temporary XML file was left behind: %s" % temp)
        data = dst.read_bytes()
        if len(data) > MAX_XML_BYTES:
            raise AssertionError("XML output is %s bytes; group walk did not stay bounded" % len(data))
        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:
            raise AssertionError("XML output is not well formed: %s" % exc) from exc
        return root


def _elements_by_id(root, guid):
    return [elem for elem in root.iter() if elem.get("id") == guid]


def _assert_once(root, guid_numbers):
    for n in guid_numbers:
        found = _elements_by_id(root, _guid(n))
        if len(found) != 1:
            raise AssertionError("GlobalId %s appears %s times, expected 1" % (_guid(n), len(found)))


def _is_ancestor(ancestor, descendant):
    for elem in ancestor.iter():
        if elem is descendant:
            return True
    return False


def _assert_nested(root, ancestor_n, descendant_n):
    ancestor = _elements_by_id(root, _guid(ancestor_n))[0]
    descendant = _elements_by_id(root, _guid(descendant_n))[0]
    if ancestor is descendant or not _is_ancestor(ancestor, descendant):
        raise AssertionError("GlobalId %s is not nested inside %s" % (_guid(descendant_n), _guid(ancestor_n)))


class XmlGroupCycleTests(unittest.TestCase):
    def test_mutual_group_cycle_emits_each_group_once(self):
        # GroupA lists GroupB and GroupB lists GroupA.
        body = "\n".join(
            [
                _group(10, 10, "GroupA"),
                _group(11, 11, "GroupB"),
                _assign(12, 12, [11], 10),
                _assign(13, 13, [10], 11),
            ]
        )
        root = _convert(_ifc(body))
        _assert_once(root, [10, 11])
        a = _elements_by_id(root, _guid(10))[0]
        b = _elements_by_id(root, _guid(11))[0]
        nested = _is_ancestor(a, b) or _is_ancestor(b, a)
        self.assertTrue(nested, "one group in the cycle must contain the other")
        self.assertFalse(_is_ancestor(a, b) and _is_ancestor(b, a))

    def test_self_grouped_group_emits_itself_once(self):
        body = "\n".join(
            [
                _group(10, 10, "Loop"),
                _assign(11, 11, [10], 10),
            ]
        )
        root = _convert(_ifc(body))
        _assert_once(root, [10])
        elem = _elements_by_id(root, _guid(10))[0]
        children = [child for child in elem.iter() if child is not elem and child.get("id") == _guid(10)]
        self.assertEqual(children, [])

    def test_three_group_cycle_emits_each_group_once(self):
        body = "\n".join(
            [
                _group(10, 10, "GroupA"),
                _group(11, 11, "GroupB"),
                _group(12, 12, "GroupC"),
                _assign(13, 13, [11], 10),
                _assign(14, 14, [12], 11),
                _assign(15, 15, [10], 12),
            ]
        )
        root = _convert(_ifc(body))
        _assert_once(root, [10, 11, 12])

    def test_system_subtype_cycle_emits_each_system_once(self):
        # IfcSystem is an IfcGroup. instances_by_type<IfcGroup> includes it,
        # and the same writeGroupToNode walk follows IsGroupedBy.
        body = "\n".join(
            [
                _group(10, 10, "SystemA", entity="IFCSYSTEM"),
                _group(11, 11, "SystemB", entity="IFCSYSTEM"),
                _assign(12, 12, [11], 10),
                _assign(13, 13, [10], 11),
            ]
        )
        root = _convert(_ifc(body))
        _assert_once(root, [10, 11])
        self.assertEqual(_elements_by_id(root, _guid(10))[0].tag, "IfcSystem")
        self.assertEqual(_elements_by_id(root, _guid(11))[0].tag, "IfcSystem")

    def test_duplicate_names_do_not_collapse_a_cycle(self):
        # Both groups are named "Same". A guard keyed only by name drops one
        # entity. Identity has to be the entity, which the XML exposes as id.
        body = "\n".join(
            [
                _group(10, 10, "Same"),
                _group(11, 11, "Same"),
                _assign(12, 12, [11], 10),
                _assign(13, 13, [10], 11),
            ]
        )
        root = _convert(_ifc(body))
        _assert_once(root, [10, 11])

    def test_acyclic_chain_nests_each_group_once(self):
        body = "\n".join(
            [
                _group(10, 10, "Root"),
                _group(11, 11, "Middle"),
                _group(12, 12, "Leaf"),
                _assign(13, 13, [11], 10),
                _assign(14, 14, [12], 11),
            ]
        )
        root = _convert(_ifc(body))
        _assert_once(root, [10, 11, 12])
        _assert_nested(root, 10, 11)
        _assert_nested(root, 11, 12)

    def test_duplicate_names_stay_nested_when_acyclic(self):
        body = "\n".join(
            [
                _group(10, 10, "Same"),
                _group(11, 11, "Same"),
                _assign(12, 12, [11], 10),
            ]
        )
        root = _convert(_ifc(body))
        _assert_once(root, [10, 11])
        _assert_nested(root, 10, 11)

    def test_repeated_assignment_emits_the_child_once(self):
        # Two IfcRelAssignsToGroup edges name the same child. The child is
        # recorded on the shared set after it is written, so the second edge
        # must not write it again.
        body = "\n".join(
            [
                _group(10, 10, "Parent"),
                _group(11, 11, "Child"),
                _assign(12, 12, [11], 10),
                _assign(13, 13, [11], 10),
            ]
        )
        root = _convert(_ifc(body))
        _assert_once(root, [10, 11])
        _assert_nested(root, 10, 11)

    def test_diamond_emits_the_shared_child_once(self):
        # Parent lists Left and Right, and both list Shared.
        body = "\n".join(
            [
                _group(10, 10, "Parent"),
                _group(11, 11, "Left"),
                _group(12, 12, "Right"),
                _group(13, 13, "Shared"),
                _assign(14, 14, [11, 12], 10),
                _assign(15, 15, [13], 11),
                _assign(16, 16, [13], 12),
            ]
        )
        root = _convert(_ifc(body))
        _assert_once(root, [10, 11, 12, 13])
        _assert_nested(root, 10, 11)
        _assert_nested(root, 10, 12)
        shared = _elements_by_id(root, _guid(13))[0]
        ancestors = [n for n in (11, 12) if _is_ancestor(_elements_by_id(root, _guid(n))[0], shared)]
        self.assertEqual(len(ancestors), 1)


if __name__ == "__main__":
    unittest.main()
