# This file was generated with the assistance of an AI coding tool.
# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2026 IfcOpenShell contributors
#
# This file is part of IfcOpenShell.
#
# IfcOpenShell is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# IfcOpenShell is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with IfcOpenShell.  If not, see <http://www.gnu.org/licenses/>.

"""IfcConvert XML export must finish when IFC graphs contain cycles.

These tests drive the IfcConvert XML serializer. Each case expects a completed
XML document that still contains the acyclic neighbours of the cycle. A stack
overflow, timeout, non-zero exit, or missing neighbour fails the test.
"""

import os
import shutil
import subprocess
import tempfile

import pytest

HEADER = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('input.ifc','1970-01-01T00:00:00',(''),(''),'IfcOpenShell','IfcOpenShell','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCPERSON($,$,'Tester',$,$,$,$,$);
#2=IFCORGANIZATION($,'Org',$,$,$);
#3=IFCPERSONANDORGANIZATION(#1,#2,$);
#4=IFCAPPLICATION(#2,'0','App','App');
#5=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
#6=IFCUNITASSIGNMENT((#5));
#7=IFCOWNERHISTORY(#3,#4,$,.ADDED.,$,$,$,0);
#8=IFCPROJECT('0lY6P5Ur90TAQnnnI6wtnb',#7,'ProjectMarker',$,$,$,$,$,#6);
"""


def _ifc(*entities: str) -> str:
    return HEADER + "\n".join(entities) + "\nENDSEC;\nEND-ISO-10303-21;\n"


def _convert(ifc_text: str) -> str:
    ifcconvert = os.environ.get("IFCCONVERT") or shutil.which("IfcConvert")
    if not ifcconvert:
        pytest.fail("IFCCONVERT is not set and IfcConvert is not on PATH")

    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "input.ifc")
        dst = os.path.join(tmp, "output.xml")
        with open(src, "w", encoding="utf-8") as handle:
            handle.write(ifc_text)
        command = ["prlimit", "--core=0", "--stack=8388608", "--", ifcconvert, src, dst]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except subprocess.TimeoutExpired as exc:
            pytest.fail(f"IfcConvert timed out\nstdout:\n{exc.stdout}\nstderr:\n{exc.stderr}")

        assert completed.returncode == 0, (
            f"IfcConvert exit {completed.returncode}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
        assert os.path.isfile(dst), "XML output was not written to the requested path"
        assert not os.path.exists(dst + ".tmp"), "temporary XML output was left behind"
        with open(dst, encoding="utf-8") as handle:
            xml = handle.read()
        assert xml.rstrip().endswith("</ifc>"), "XML output is incomplete"
        assert 'Name="ProjectMarker"' in xml
        return xml


def test_cyclic_complex_properties_are_exported():
    xml = _convert(
        _ifc(
            "#10=IFCPROPERTYSINGLEVALUE('SiblingMarker',$,IFCLABEL('sibling-visible'),$);",
            "#11=IFCPROPERTYSINGLEVALUE('SelfLeaf',$,IFCLABEL('self-leaf'),$);",
            "#12=IFCCOMPLEXPROPERTY('SelfCycle',$,'Usage',(#12,#11));",
            "#13=IFCPROPERTYSET('1lY6P5Ur90TAQnnnI6wtnb',#7,'PsetSelf',$,(#12,#10));",
            "#14=IFCPROPERTYSINGLEVALUE('OrderedLeaf',$,IFCLABEL('ordered-leaf'),$);",
            "#15=IFCCOMPLEXPROPERTY('OrderedCycle',$,'Usage',(#14,#15));",
            "#16=IFCPROPERTYSET('2lY6P5Ur90TAQnnnI6wtnb',#7,'PsetOrdered',$,(#15));",
            "#20=IFCPROPERTYSINGLEVALUE('MutualLeaf',$,IFCLABEL('mutual-leaf'),$);",
            "#21=IFCCOMPLEXPROPERTY('MutualA',$,'UsageA',(#22,#20));",
            "#22=IFCCOMPLEXPROPERTY('MutualB',$,'UsageB',(#21));",
            "#23=IFCPROPERTYSET('3lY6P5Ur90TAQnnnI6wtnb',#7,'PsetMutual',$,(#21));",
            "#30=IFCPROPERTYSINGLEVALUE('AcyclicLeaf',$,IFCLABEL('acyclic-leaf'),$);",
            "#31=IFCCOMPLEXPROPERTY('Depth3',$,'U3',(#30));",
            "#32=IFCCOMPLEXPROPERTY('Depth2',$,'U2',(#31));",
            "#33=IFCCOMPLEXPROPERTY('Depth1',$,'U1',(#32));",
            "#34=IFCPROPERTYSET('4lY6P5Ur90TAQnnnI6wtnb',#7,'PsetAcyclic',$,(#33));",
            "#40=IFCPROPERTYSINGLEVALUE('DiamondLeaf',$,IFCLABEL('diamond-leaf'),$);",
            "#41=IFCCOMPLEXPROPERTY('DiamondChild',$,'Uc',(#40));",
            "#42=IFCCOMPLEXPROPERTY('DiamondLeft',$,'Ul',(#41));",
            "#43=IFCCOMPLEXPROPERTY('DiamondRight',$,'Ur',(#41));",
            "#44=IFCPROPERTYSET('5lY6P5Ur90TAQnnnI6wtnb',#7,'PsetDiamond',$,(#42,#43));",
        )
    )
    for marker in (
        'Name="SiblingMarker"',
        'NominalValue="sibling-visible"',
        'Name="SelfLeaf"',
        'NominalValue="self-leaf"',
        'Name="OrderedLeaf"',
        'NominalValue="ordered-leaf"',
        'Name="MutualLeaf"',
        'NominalValue="mutual-leaf"',
        'Name="AcyclicLeaf"',
        'NominalValue="acyclic-leaf"',
        'Name="DiamondLeaf"',
        'NominalValue="diamond-leaf"',
    ):
        assert marker in xml


def test_cyclic_complex_quantities_are_exported():
    xml = _convert(
        _ifc(
            "#50=IFCQUANTITYLENGTH('QuantitySelfLeaf',$,$,1.25,$);",
            "#51=IFCPHYSICALCOMPLEXQUANTITY('QSelf',$,(#50,#51),'layer',$,$);",
            "#52=IFCQUANTITYLENGTH('QuantitySibling',$,$,3.5,$);",
            "#53=IFCELEMENTQUANTITY('4lY6P5Ur90TAQnnnI6wtnb',#7,'QtoSelf',$,$,(#51,#52));",
            "#60=IFCQUANTITYLENGTH('QuantityMutualLeaf',$,$,2.5,$);",
            "#61=IFCPHYSICALCOMPLEXQUANTITY('QA',$,(#62,#60),'layer',$,$);",
            "#62=IFCPHYSICALCOMPLEXQUANTITY('QB',$,(#61),'layer',$,$);",
            "#63=IFCELEMENTQUANTITY('5lY6P5Ur90TAQnnnI6wtnb',#7,'QtoMutual',$,$,(#61));",
            "#70=IFCQUANTITYLENGTH('QuantityNestedLeaf',$,$,4.5,$);",
            "#71=IFCPHYSICALCOMPLEXQUANTITY('QDepth2',$,(#70),'layer',$,$);",
            "#72=IFCPHYSICALCOMPLEXQUANTITY('QDepth1',$,(#71),'layer',$,$);",
            "#73=IFCELEMENTQUANTITY('6lY6P5Ur90TAQnnnI6wtnb',#7,'QtoNested',$,$,(#72));",
        )
    )
    for marker in (
        'Name="QuantitySelfLeaf"',
        'LengthValue="1.25"',
        'Name="QuantitySibling"',
        'LengthValue="3.5"',
        'Name="QuantityMutualLeaf"',
        'LengthValue="2.5"',
        'Name="QuantityNestedLeaf"',
        'LengthValue="4.5"',
    ):
        assert marker in xml


def test_cyclic_nested_tasks_are_exported():
    xml = _convert(
        _ifc(
            "#10=IFCTASK('5lY6P5Ur90TAQnnnI6wtnb',#7,'TaskSelf',$,$,$,$,$,$,.F.,$,$,$);",
            "#11=IFCTASK('6lY6P5Ur90TAQnnnI6wtnb',#7,'TaskSelfSibling',$,$,$,$,$,$,.F.,$,$,$);",
            "#12=IFCRELNESTS('7lY6P5Ur90TAQnnnI6wtnb',#7,$,$,#10,(#10,#11));",
            "#13=IFCWORKSCHEDULE('8lY6P5Ur90TAQnnnI6wtnb',#7,'SchedSelf',$,$,$,'2020-01-01',$,$,$,$,'2020-01-01',$,$);",
            "#14=IFCRELASSIGNSTOCONTROL('9lY6P5Ur90TAQnnnI6wtnb',#7,$,$,(#10),$,#13);",
            "#20=IFCTASK('AlY6P5Ur90TAQnnnI6wtn1',#7,'TaskA',$,$,$,$,$,$,.F.,$,$,$);",
            "#21=IFCTASK('BlY6P5Ur90TAQnnnI6wtn2',#7,'TaskB',$,$,$,$,$,$,.F.,$,$,$);",
            "#22=IFCTASK('ClY6P5Ur90TAQnnnI6wtn3',#7,'TaskMutualSibling',$,$,$,$,$,$,.F.,$,$,$);",
            "#23=IFCRELNESTS('DlY6P5Ur90TAQnnnI6wtn4',#7,$,$,#20,(#21));",
            "#24=IFCRELNESTS('ElY6P5Ur90TAQnnnI6wtn5',#7,$,$,#21,(#20,#22));",
            "#25=IFCWORKSCHEDULE('FlY6P5Ur90TAQnnnI6wtn6',#7,'SchedMutual',$,$,$,'2020-01-01',$,$,$,$,'2020-01-01',$,$);",
            "#26=IFCRELASSIGNSTOCONTROL('GlY6P5Ur90TAQnnnI6wtn7',#7,$,$,(#20),$,#25);",
        )
    )
    assert 'Name="TaskSelfSibling"' in xml
    assert 'Name="TaskMutualSibling"' in xml


def test_cyclic_groups_are_exported():
    xml = _convert(
        _ifc(
            "#10=IFCGROUP('5lY6P5Ur90TAQnnnI6wtnb',#7,'GroupSelf',$,$);",
            "#11=IFCGROUP('6lY6P5Ur90TAQnnnI6wtnb',#7,'GroupSelfSibling',$,$);",
            "#12=IFCRELASSIGNSTOGROUP('7lY6P5Ur90TAQnnnI6wtnb',#7,$,$,(#10,#11),$,#10);",
            "#20=IFCGROUP('AlY6P5Ur90TAQnnnI6wtn1',#7,'GroupA',$,$);",
            "#21=IFCGROUP('BlY6P5Ur90TAQnnnI6wtn2',#7,'GroupB',$,$);",
            "#22=IFCGROUP('ClY6P5Ur90TAQnnnI6wtn3',#7,'GroupMutualSibling',$,$);",
            "#23=IFCRELASSIGNSTOGROUP('DlY6P5Ur90TAQnnnI6wtn4',#7,$,$,(#21),$,#20);",
            "#24=IFCRELASSIGNSTOGROUP('ElY6P5Ur90TAQnnnI6wtn5',#7,$,$,(#20,#22),$,#21);",
        )
    )
    assert 'Name="GroupSelfSibling"' in xml
    assert 'Name="GroupMutualSibling"' in xml


def test_cyclic_spatial_decomposition_is_exported():
    xml = _convert(
        _ifc(
            "#10=IFCSITE('5lY6P5Ur90TAQnnnI6wtnb',#7,'SiteCycle',$,$,$,$,$,$,$,$,$,$,$);",
            "#11=IFCBUILDING('6lY6P5Ur90TAQnnnI6wtnb',#7,'BuildingSibling',$,$,$,$,$,$,$,$,$);",
            "#12=IFCRELAGGREGATES('7lY6P5Ur90TAQnnnI6wtnb',#7,$,$,#8,(#8,#10));",
            "#13=IFCRELAGGREGATES('8lY6P5Ur90TAQnnnI6wtnb',#7,$,$,#10,(#8,#11));",
        )
    )
    assert 'Name="BuildingSibling"' in xml
    assert 'Name="SiteCycle"' in xml


def test_cyclic_type_decomposition_is_exported():
    xml = _convert(
        _ifc(
            "#10=IFCWALLTYPE('5lY6P5Ur90TAQnnnI6wtnb',#7,'TypeParent',$,$,$,$,$,$,.STANDARD.);",
            "#11=IFCWALLTYPE('6lY6P5Ur90TAQnnnI6wtnb',#7,'TypeSibling',$,$,$,$,$,$,.STANDARD.);",
            "#12=IFCRELAGGREGATES('7lY6P5Ur90TAQnnnI6wtnb',#7,$,$,#10,(#10,#11));",
            "#20=IFCWALLTYPE('AlY6P5Ur90TAQnnnI6wtn1',#7,'TypeA',$,$,$,$,$,$,.STANDARD.);",
            "#21=IFCWALLTYPE('BlY6P5Ur90TAQnnnI6wtn2',#7,'TypeB',$,$,$,$,$,$,.STANDARD.);",
            "#22=IFCWALLTYPE('ClY6P5Ur90TAQnnnI6wtn3',#7,'TypeMutualSibling',$,$,$,$,$,$,.STANDARD.);",
            "#23=IFCRELAGGREGATES('DlY6P5Ur90TAQnnnI6wtn4',#7,$,$,#20,(#21));",
            "#24=IFCRELAGGREGATES('ElY6P5Ur90TAQnnnI6wtn5',#7,$,$,#21,(#20,#22));",
        )
    )
    assert 'Name="TypeSibling"' in xml
    assert 'Name="TypeMutualSibling"' in xml
