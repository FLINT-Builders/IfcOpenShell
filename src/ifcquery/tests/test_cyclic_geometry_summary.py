# This file was generated with the assistance of an AI coding tool.
# IfcQuery - IFC model interrogation CLI
# Copyright (C) 2026 Bruno Postle <bruno@postle.net>
#
# This file is part of IfcQuery.
#
# IfcQuery is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# IfcQuery is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with IfcQuery.  If not, see <http://www.gnu.org/licenses/>.

"""Geometry summaries of cyclic booleans and mapped items have to finish."""

import signal
from pathlib import Path

import ifcopenshell
import pytest

from ifcquery.info import _summarize_rep, _walk_clipping, info

_HEADER = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('cycle.ifc','2024-01-01T00:00:00',(''),(''),'test','test','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
"""


class WalkDidNotFinish(BaseException):
    pass


def _on_alarm(signum, frame):
    raise WalkDidNotFinish()


def assert_finishes(fn, seconds=1.0):
    previous = signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return fn()
    except WalkDidNotFinish:
        pytest.fail(f"geometry summary did not finish within {seconds}s")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def open_data(tmp_path: Path, data: str) -> ifcopenshell.file:
    path = tmp_path / "model.ifc"
    path.write_text(_HEADER + data + "ENDSEC;\nEND-ISO-10303-21;\n")
    return ifcopenshell.open(path)


def test_clipping_cycle_summary_finishes(tmp_path):
    model = open_data(
        tmp_path,
        """\
#1=IFCCARTESIANPOINT((0.,0.,0.));
#2=IFCAXIS2PLACEMENT3D(#1,$,$);
#10=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#2,$);
#11=IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,#10,$,.MODEL_VIEW.,$);
#30=IFCPLANE(#2);
#31=IFCHALFSPACESOLID(#30,.T.);
#32=IFCBOOLEANCLIPPINGRESULT(.DIFFERENCE.,#32,#31);
#33=IFCSHAPEREPRESENTATION(#11,'Body','Clipping',(#32));
#34=IFCPRODUCTDEFINITIONSHAPE($,$,(#33));
#35=IFCWALL('1U7MoqHmr8YP6jwz0pc7e0',$,'Wall',$,$,$,#34,$);
""",
    )
    base, planes = assert_finishes(lambda: _walk_clipping(model.by_id(32)))
    assert base.id() == 32
    assert len(planes) <= 1
    summary = assert_finishes(lambda: info(model, model.by_id(35)))
    assert summary["geometry_summary"]["representation_type"] == "Clipping"
    assert len(summary["geometry_summary"]["solids"]) == 1


def test_mapped_cycle_summary_finishes(tmp_path):
    model = open_data(
        tmp_path,
        """\
#1=IFCCARTESIANPOINT((0.,0.,0.));
#2=IFCAXIS2PLACEMENT3D(#1,$,$);
#10=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#2,$);
#31=IFCCARTESIANTRANSFORMATIONOPERATOR3D($,$,#1,$,$);
#32=IFCSHAPEREPRESENTATION(#10,'Body','MappedRepresentation',(#33));
#33=IFCMAPPEDITEM(#34,#31);
#34=IFCREPRESENTATIONMAP(#2,#32);
#35=IFCPRODUCTDEFINITIONSHAPE($,$,(#32));
#36=IFCWALL('1U7MoqHmr8YP6jwz0pc7e0',$,'Wall',$,$,$,#35,$);
""",
    )
    summary = assert_finishes(lambda: _summarize_rep(model.by_id(32)))
    assert summary["representation_type"] == "MappedRepresentation"
    inspected = assert_finishes(lambda: info(model, model.by_id(36)))
    assert inspected["geometry_summary"]["representation_type"] == "MappedRepresentation"
