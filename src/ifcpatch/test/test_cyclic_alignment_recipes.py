# This file was generated with the assistance of an AI coding tool.

import os
import tempfile

import ifcopenshell
import ifcopenshell.guid
import pytest

import ifcpatch

try:
    ifcopenshell.file(schema="IFC4X3")
    IFC4X3_AVAILABLE = True
except RuntimeError:
    IFC4X3_AVAILABLE = False


def _open_mutual_cycle() -> ifcopenshell.file:
    model = ifcopenshell.file(schema="IFC4X3")
    first = model.create_entity("IfcAlignment", GlobalId=ifcopenshell.guid.new(), Name="A0")
    second = model.create_entity("IfcAlignment", GlobalId=ifcopenshell.guid.new(), Name="A1")
    model.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=first,
        RelatedObjects=[second],
    )
    model.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=second,
        RelatedObjects=[first],
    )
    descriptor, path = tempfile.mkstemp(suffix=".ifc")
    os.close(descriptor)
    try:
        model.write(path)
        return ifcopenshell.open(path)
    finally:
        os.unlink(path)


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_patch_station_referent_position_does_not_recurse_on_cyclic_alignments():
    model = _open_mutual_cycle()
    alignments = model.by_type("IfcAlignment")
    assert len(alignments) == 2
    for alignment in alignments:
        assert alignment.Representation is None
        assert alignment.Decomposes[0].RelatingObject in alignments
        assert alignment.Decomposes[0].RelatingObject != alignment

    # The recipe looks up a basis curve before it indexes stationing nests.
    # A cycle must stop at the lookup. With no nests, the next statement is
    # an IndexError, which shows the lookup returned.
    with pytest.raises(IndexError):
        ifcpatch.execute({"file": model, "recipe": "PatchStationReferentPosition"})
