# This file was generated with the assistance of an AI coding tool.
"""IfcConvert document export must finish when IFC relationships form a cycle.

The XML and JSON exporters walk containment, aggregation, nesting, fills, and
openings by recursion, and the XML exporter also recurses through grouped
objects, nested tasks, complex properties, and complex quantities. None of
those walks record the entities already emitted. A file that points two of
those relationships at each other exhausts the process stack, and IfcConvert
dies with SIGSEGV before it writes the output.

These tests fail while that behavior is present. After the walks skip an
entity they have already emitted (or emit a single cycle marker), IfcConvert
exits 0 and writes a small, well-formed document in which every tracked id
appears at least once and at most twice.

Run, from a build that includes the IFC2X3 and IFC4 document serializers
(JSON cases also need GLTF_SUPPORT):

    IFCCONVERT=/path/to/IfcConvert python3 -m unittest src/ifcconvert/tests/test_cyclic_document_export.py
"""

import json
import os
import resource
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_OUTPUT_BYTES = 1_000_000
MAX_ID_OCCURRENCES = 2
STACK_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 30

HEADER = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('cycle.ifc','2024-01-01T00:00:00',(''),(''),'test','test','');
FILE_SCHEMA(('{schema}'));
ENDSEC;
DATA;
#1=IFCPROJECT('0$project0000000000000',$,'Project',$,$,$,$,{contexts},#2);
#2=IFCUNITASSIGNMENT((#3));
#3=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
{body}
ENDSEC;
END-ISO-10303-21;
"""


def _ifcconvert():
    configured = os.environ.get("IFCCONVERT")
    if configured:
        if not os.path.isfile(configured) or not os.access(configured, os.X_OK):
            raise AssertionError("IFCCONVERT is not an executable file: " + configured)
        return configured
    found = shutil.which("IfcConvert")
    if found:
        return found
    root = Path(__file__).resolve().parents[3]
    for candidate in (
        root / "build" / "ifcconvert" / "IfcConvert",
        root / "cmake-build-release" / "ifcconvert" / "IfcConvert",
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise AssertionError("Set IFCCONVERT to an IfcConvert built from this tree")


def _limit_stack():
    resource.setrlimit(resource.RLIMIT_STACK, (STACK_BYTES, STACK_BYTES))


class CyclicDocumentExportTests(unittest.TestCase):
    def convert(self, schema, extension, body, tracked_ids):
        ifcconvert = _ifcconvert()
        contexts = "()" if schema == "IFC2X3" else "$"
        ifc = HEADER.format(schema=schema, contexts=contexts, body=body.strip())
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "model.ifc")
            output = os.path.join(directory, "model" + extension)
            with open(source, "w", encoding="ascii") as handle:
                handle.write(ifc)
            try:
                completed = subprocess.run(
                    [ifcconvert, source, output],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=TIMEOUT_SECONDS,
                    preexec_fn=_limit_stack,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                self.fail("IfcConvert did not finish within %s seconds: %s" % (TIMEOUT_SECONDS, exc))
            transcript = completed.stdout.decode(errors="replace")
            self.assertEqual(
                completed.returncode,
                0,
                "IfcConvert exited %s for %s %s\n%s" % (completed.returncode, schema, extension, transcript),
            )
            self.assertTrue(os.path.isfile(output), "IfcConvert wrote no output\n" + transcript)
            size = os.path.getsize(output)
            self.assertLess(size, MAX_OUTPUT_BYTES, "output is %s bytes" % size)
            with open(output, encoding="utf-8") as handle:
                text = handle.read()
            if extension == ".xml":
                ET.fromstring(text)
            else:
                json.loads(text)
            for entity_id in tracked_ids:
                occurrences = text.count(entity_id)
                self.assertGreaterEqual(occurrences, 1, entity_id + " was not exported")
                self.assertLessEqual(
                    occurrences,
                    MAX_ID_OCCURRENCES,
                    "%s was exported %s times" % (entity_id, occurrences),
                )


def _case(name, schema, extension, body, tracked_ids):
    def test(self):
        self.convert(schema, extension, body, tracked_ids)

    test.__name__ = name
    return test


# WallA fills two openings, so the single-fill early return in descend does
# not apply and the opening/fill cycle is actually walked.
OPENING_CYCLE_IFC4 = """
#4=IFCWALL('1$wallA00000000000000',$,'WallA',$,$,$,$,$,$);
#5=IFCWALL('2$wallB00000000000000',$,'WallB',$,$,$,$,$,$);
#6=IFCOPENINGELEMENT('3$openA00000000000000',$,'OpenA',$,$,$,$,$,$);
#7=IFCOPENINGELEMENT('4$openB00000000000000',$,'OpenB',$,$,$,$,$,$);
#8=IFCOPENINGELEMENT('5$openD00000000000000',$,'OpenD',$,$,$,$,$,$);
#9=IFCBUILDINGSTOREY('3$storeyKeep00000000',$,'KeepMe',$,$,$,$,$,$,$);
#10=IFCRELAGGREGATES('6$relproj0000000000000',$,$,$,#1,(#4,#9));
#11=IFCRELVOIDSELEMENT('7$voidA00000000000000',$,$,$,#4,#6);
#12=IFCRELVOIDSELEMENT('8$voidB00000000000000',$,$,$,#5,#7);
#13=IFCRELVOIDSELEMENT('9$voidD00000000000000',$,$,$,#5,#8);
#14=IFCRELFILLSELEMENT('A$fillB00000000000000',$,$,$,#7,#4);
#15=IFCRELFILLSELEMENT('B$fillD00000000000000',$,$,$,#8,#4);
#16=IFCRELFILLSELEMENT('C$fillA00000000000000',$,$,$,#6,#5);
"""

OPENING_CYCLE_IFC2X3 = """
#4=IFCWALL('1$wallA00000000000000',$,'WallA',$,$,$,$,$);
#5=IFCWALL('2$wallB00000000000000',$,'WallB',$,$,$,$,$);
#6=IFCOPENINGELEMENT('3$openA00000000000000',$,'OpenA',$,$,$,$,$);
#7=IFCOPENINGELEMENT('4$openB00000000000000',$,'OpenB',$,$,$,$,$);
#8=IFCOPENINGELEMENT('5$openD00000000000000',$,'OpenD',$,$,$,$,$);
#9=IFCBUILDINGSTOREY('3$storeyKeep00000000',$,'KeepMe',$,$,$,$,$,.ELEMENT.,$);
#10=IFCRELAGGREGATES('6$relproj0000000000000',$,$,$,#1,(#4,#9));
#11=IFCRELVOIDSELEMENT('7$voidA00000000000000',$,$,$,#4,#6);
#12=IFCRELVOIDSELEMENT('8$voidB00000000000000',$,$,$,#5,#7);
#13=IFCRELVOIDSELEMENT('9$voidD00000000000000',$,$,$,#5,#8);
#14=IFCRELFILLSELEMENT('A$fillB00000000000000',$,$,$,#7,#4);
#15=IFCRELFILLSELEMENT('B$fillD00000000000000',$,$,$,#8,#4);
#16=IFCRELFILLSELEMENT('C$fillA00000000000000',$,$,$,#6,#5);
"""

CASES = [
    (
        "test_ifc4_xml_acyclic_aggregation",
        "IFC4",
        ".xml",
        """
#4=IFCBUILDINGSTOREY('1$storeyA000000000000',$,'StoreyA',$,$,$,$,$,$,$);
#5=IFCBUILDINGSTOREY('3$storeyKeep00000000',$,'KeepMe',$,$,$,$,$,$,$);
#7=IFCRELAGGREGATES('4$relproj0000000000000',$,$,$,#1,(#4,#5));
""",
        ("1$storeyA000000000000", "3$storeyKeep00000000"),
    ),
    (
        "test_ifc4_xml_aggregation_cycle",
        "IFC4",
        ".xml",
        """
#4=IFCBUILDINGSTOREY('1$storeyA000000000000',$,'StoreyA',$,$,$,$,$,$,$);
#5=IFCBUILDINGSTOREY('2$storeyB000000000000',$,'StoreyB',$,$,$,$,$,$,$);
#6=IFCBUILDINGSTOREY('3$storeyKeep00000000',$,'KeepMe',$,$,$,$,$,$,$);
#7=IFCRELAGGREGATES('4$relproj0000000000000',$,$,$,#1,(#4,#6));
#8=IFCRELAGGREGATES('5$relA0000000000000000',$,$,$,#4,(#5));
#9=IFCRELAGGREGATES('6$relB0000000000000000',$,$,$,#5,(#4));
""",
        ("1$storeyA000000000000", "2$storeyB000000000000", "3$storeyKeep00000000"),
    ),
    (
        "test_ifc4_xml_self_aggregation",
        "IFC4",
        ".xml",
        """
#4=IFCBUILDINGSTOREY('1$storeyA000000000000',$,'StoreyA',$,$,$,$,$,$,$);
#6=IFCBUILDINGSTOREY('3$storeyKeep00000000',$,'KeepMe',$,$,$,$,$,$,$);
#7=IFCRELAGGREGATES('4$relproj0000000000000',$,$,$,#1,(#4,#6));
#8=IFCRELAGGREGATES('5$relA0000000000000000',$,$,$,#4,(#4));
""",
        ("1$storeyA000000000000", "3$storeyKeep00000000"),
    ),
    (
        "test_ifc4_xml_containment_cycle",
        "IFC4",
        ".xml",
        """
#4=IFCBUILDINGSTOREY('1$storeyA000000000000',$,'StoreyA',$,$,$,$,$,$,$);
#5=IFCBUILDINGSTOREY('2$storeyB000000000000',$,'StoreyB',$,$,$,$,$,$,$);
#6=IFCBUILDINGSTOREY('3$storeyKeep00000000',$,'KeepMe',$,$,$,$,$,$,$);
#7=IFCRELAGGREGATES('4$relproj0000000000000',$,$,$,#1,(#4,#6));
#8=IFCRELCONTAINEDINSPATIALSTRUCTURE('5$relA0000000000000000',$,$,$,(#5),#4);
#9=IFCRELCONTAINEDINSPATIALSTRUCTURE('6$relB0000000000000000',$,$,$,(#4),#5);
""",
        ("1$storeyA000000000000", "2$storeyB000000000000", "3$storeyKeep00000000"),
    ),
    (
        "test_ifc4_xml_nesting_cycle",
        "IFC4",
        ".xml",
        """
#4=IFCBUILDINGELEMENTPROXY('1$proxyA0000000000000',$,'ProxyA',$,$,$,$,$,$);
#5=IFCBUILDINGELEMENTPROXY('2$proxyB0000000000000',$,'ProxyB',$,$,$,$,$,$);
#6=IFCBUILDINGSTOREY('3$storeyKeep00000000',$,'KeepMe',$,$,$,$,$,$,$);
#7=IFCRELAGGREGATES('4$relproj0000000000000',$,$,$,#1,(#4,#6));
#8=IFCRELNESTS('5$relA0000000000000000',$,$,$,#4,(#5));
#9=IFCRELNESTS('6$relB0000000000000000',$,$,$,#5,(#4));
""",
        ("1$proxyA0000000000000", "2$proxyB0000000000000", "3$storeyKeep00000000"),
    ),
    (
        "test_ifc4_xml_opening_fill_cycle",
        "IFC4",
        ".xml",
        OPENING_CYCLE_IFC4,
        ("1$wallA00000000000000", "2$wallB00000000000000", "3$openA00000000000000", "3$storeyKeep00000000"),
    ),
    (
        "test_ifc4_xml_mutual_single_fill_exports",
        "IFC4",
        ".xml",
        """
#4=IFCWALL('1$wallA00000000000000',$,'WallA',$,$,$,$,$,$);
#5=IFCWALL('2$wallB00000000000000',$,'WallB',$,$,$,$,$,$);
#6=IFCOPENINGELEMENT('3$openA00000000000000',$,'OpenA',$,$,$,$,$,$);
#7=IFCOPENINGELEMENT('4$openB00000000000000',$,'OpenB',$,$,$,$,$,$);
#10=IFCRELAGGREGATES('6$relproj0000000000000',$,$,$,#1,(#4));
#11=IFCRELVOIDSELEMENT('7$voidA00000000000000',$,$,$,#4,#6);
#12=IFCRELVOIDSELEMENT('8$voidB00000000000000',$,$,$,#5,#7);
#14=IFCRELFILLSELEMENT('A$fillB00000000000000',$,$,$,#7,#4);
#16=IFCRELFILLSELEMENT('C$fillA00000000000000',$,$,$,#6,#5);
""",
        ("0$project0000000000000",),
    ),
    (
        "test_ifc4_xml_type_aggregation_cycle",
        "IFC4",
        ".xml",
        """
#4=IFCWALLTYPE('1$typeA00000000000000',$,'TypeA',$,$,$,$,$,$,.STANDARD.);
#5=IFCWALLTYPE('2$typeB00000000000000',$,'TypeB',$,$,$,$,$,$,.STANDARD.);
#6=IFCWALLTYPE('3$typeKeep00000000000',$,'TypeKeep',$,$,$,$,$,$,.STANDARD.);
#7=IFCRELAGGREGATES('4$relA0000000000000000',$,$,$,#4,(#5));
#8=IFCRELAGGREGATES('5$relB0000000000000000',$,$,$,#5,(#4));
""",
        ("1$typeA00000000000000", "2$typeB00000000000000", "3$typeKeep00000000000"),
    ),
    (
        "test_ifc4_xml_task_nesting_cycle",
        "IFC4",
        ".xml",
        """
#4=IFCWORKSCHEDULE('1$sched00000000000000',$,'Sched',$,$,$,'2020-01-01',$,$,$,$,'2020-01-01',$,$);
#5=IFCTASK('2$taskA00000000000000',$,'TaskA',$,$,$,$,$,$,.F.,$,$,$);
#6=IFCTASK('3$taskB00000000000000',$,'TaskB',$,$,$,$,$,$,.F.,$,$,$);
#7=IFCTASK('4$taskKeep00000000000',$,'KeepTask',$,$,$,$,$,$,.F.,$,$,$);
#8=IFCRELASSIGNSTOCONTROL('5$asgA000000000000000',$,$,$,(#5),$,#4);
#9=IFCRELASSIGNSTOCONTROL('6$asgK000000000000000',$,$,$,(#7),$,#4);
#10=IFCRELNESTS('7$nestA00000000000000',$,$,$,#5,(#6));
#11=IFCRELNESTS('8$nestB00000000000000',$,$,$,#6,(#5));
""",
        ("2$taskA00000000000000", "3$taskB00000000000000", "4$taskKeep00000000000"),
    ),
    (
        "test_ifc4_xml_group_cycle",
        "IFC4",
        ".xml",
        """
#4=IFCGROUP('1$groupA0000000000000',$,'GroupA',$,$);
#5=IFCGROUP('2$groupB0000000000000',$,'GroupB',$,$);
#6=IFCGROUP('3$groupKeep000000000',$,'KeepGroup',$,$);
#7=IFCRELASSIGNSTOGROUP('4$asgA000000000000000',$,$,$,(#5),$,#4);
#8=IFCRELASSIGNSTOGROUP('5$asgB000000000000000',$,$,$,(#4),$,#5);
""",
        ("1$groupA0000000000000", "2$groupB0000000000000", "3$groupKeep000000000"),
    ),
    (
        "test_ifc4_xml_complex_property_cycle",
        "IFC4",
        ".xml",
        """
#10=IFCCOMPLEXPROPERTY('Cycle',$,'Usage',(#10));
#12=IFCPROPERTYSINGLEVALUE('KeepProp',$,IFCLABEL('ok'),$);
#11=IFCPROPERTYSET('1$pset000000000000000',$,'Pset',$,(#12,#10));
""",
        ("KeepProp", "Cycle"),
    ),
    (
        "test_ifc4_xml_complex_quantity_cycle",
        "IFC4",
        ".xml",
        """
#10=IFCPHYSICALCOMPLEXQUANTITY('CycleQty',$,(#10),'Disc',$,$);
#12=IFCQUANTITYLENGTH('KeepQty',$,$,10.,$);
#11=IFCELEMENTQUANTITY('1$qto000000000000000',$,'Qto',$,$,(#12,#10));
""",
        ("KeepQty", "CycleQty"),
    ),
    (
        "test_ifc2x3_xml_aggregation_cycle",
        "IFC2X3",
        ".xml",
        """
#4=IFCBUILDINGSTOREY('1$storeyA000000000000',$,'StoreyA',$,$,$,$,$,.ELEMENT.,$);
#5=IFCBUILDINGSTOREY('2$storeyB000000000000',$,'StoreyB',$,$,$,$,$,.ELEMENT.,$);
#6=IFCBUILDINGSTOREY('3$storeyKeep00000000',$,'KeepMe',$,$,$,$,$,.ELEMENT.,$);
#7=IFCRELAGGREGATES('4$relproj0000000000000',$,$,$,#1,(#4,#6));
#8=IFCRELAGGREGATES('5$relA0000000000000000',$,$,$,#4,(#5));
#9=IFCRELAGGREGATES('6$relB0000000000000000',$,$,$,#5,(#4));
""",
        ("1$storeyA000000000000", "2$storeyB000000000000", "3$storeyKeep00000000"),
    ),
    (
        "test_ifc2x3_xml_containment_cycle",
        "IFC2X3",
        ".xml",
        """
#4=IFCBUILDINGSTOREY('1$storeyA000000000000',$,'StoreyA',$,$,$,$,$,.ELEMENT.,$);
#5=IFCBUILDINGSTOREY('2$storeyB000000000000',$,'StoreyB',$,$,$,$,$,.ELEMENT.,$);
#6=IFCBUILDINGSTOREY('3$storeyKeep00000000',$,'KeepMe',$,$,$,$,$,.ELEMENT.,$);
#7=IFCRELAGGREGATES('4$relproj0000000000000',$,$,$,#1,(#4,#6));
#8=IFCRELCONTAINEDINSPATIALSTRUCTURE('5$relA0000000000000000',$,$,$,(#5),#4);
#9=IFCRELCONTAINEDINSPATIALSTRUCTURE('6$relB0000000000000000',$,$,$,(#4),#5);
""",
        ("1$storeyA000000000000", "2$storeyB000000000000", "3$storeyKeep00000000"),
    ),
    (
        "test_ifc2x3_xml_nesting_cycle",
        "IFC2X3",
        ".xml",
        """
#4=IFCBUILDINGELEMENTPROXY('1$proxyA0000000000000',$,'ProxyA',$,$,$,$,$);
#5=IFCBUILDINGELEMENTPROXY('2$proxyB0000000000000',$,'ProxyB',$,$,$,$,$);
#6=IFCBUILDINGSTOREY('3$storeyKeep00000000',$,'KeepMe',$,$,$,$,$,.ELEMENT.,$);
#7=IFCRELAGGREGATES('4$relproj0000000000000',$,$,$,#1,(#4,#6));
#8=IFCRELNESTS('5$relA0000000000000000',$,$,$,#4,(#5));
#9=IFCRELNESTS('6$relB0000000000000000',$,$,$,#5,(#4));
""",
        ("1$proxyA0000000000000", "2$proxyB0000000000000", "3$storeyKeep00000000"),
    ),
    (
        "test_ifc2x3_xml_opening_fill_cycle",
        "IFC2X3",
        ".xml",
        OPENING_CYCLE_IFC2X3,
        ("1$wallA00000000000000", "2$wallB00000000000000", "3$storeyKeep00000000"),
    ),
    (
        "test_ifc2x3_xml_group_cycle",
        "IFC2X3",
        ".xml",
        """
#4=IFCGROUP('1$groupA0000000000000',$,'GroupA',$,$);
#5=IFCGROUP('2$groupB0000000000000',$,'GroupB',$,$);
#6=IFCGROUP('3$groupKeep000000000',$,'KeepGroup',$,$);
#7=IFCRELASSIGNSTOGROUP('4$asgA000000000000000',$,$,$,(#5),$,#4);
#8=IFCRELASSIGNSTOGROUP('5$asgB000000000000000',$,$,$,(#4),$,#5);
""",
        ("1$groupA0000000000000", "2$groupB0000000000000", "3$groupKeep000000000"),
    ),
    (
        "test_ifc2x3_xml_acyclic_aggregation",
        "IFC2X3",
        ".xml",
        """
#4=IFCBUILDINGSTOREY('1$storeyA000000000000',$,'StoreyA',$,$,$,$,$,.ELEMENT.,$);
#7=IFCRELAGGREGATES('4$relproj0000000000000',$,$,$,#1,(#4));
""",
        ("1$storeyA000000000000",),
    ),
]

JSON_BODIES = [
    ("aggregation_cycle", "test_ifc4_xml_aggregation_cycle"),
    ("containment_cycle", "test_ifc4_xml_containment_cycle"),
    ("nesting_cycle", "test_ifc4_xml_nesting_cycle"),
    ("opening_fill_cycle", "test_ifc4_xml_opening_fill_cycle"),
]

# JSON uses the same relationship bodies as the XML cases above. The bodies
# are copied by name after the XML cases are registered.
_BODY_BY_TEST = {item[0]: item[3] for item in CASES}

for label, source_name in JSON_BODIES:
    source = next(item for item in CASES if item[0] == source_name)
    CASES.append(
        (
            "test_ifc4_json_" + label,
            "IFC4",
            ".json",
            source[3],
            source[4],
        )
    )
    ifc2x3_name = source_name.replace("test_ifc4_xml_", "test_ifc2x3_xml_")
    source_2x3 = next(item for item in CASES if item[0] == ifc2x3_name)
    CASES.append(
        (
            "test_ifc2x3_json_" + label,
            "IFC2X3",
            ".json",
            source_2x3[3],
            source_2x3[4],
        )
    )

CASES.append(
    (
        "test_ifc4_json_acyclic_aggregation",
        "IFC4",
        ".json",
        _BODY_BY_TEST["test_ifc4_xml_acyclic_aggregation"],
        ("1$storeyA000000000000", "3$storeyKeep00000000"),
    )
)

for name, schema, extension, body, tracked_ids in CASES:
    setattr(CyclicDocumentExportTests, name, _case(name, schema, extension, body, tracked_ids))


if __name__ == "__main__":
    unittest.main()
