# This file was generated with the assistance of an AI coding tool.
# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2021 Thomas Krijnen <thomas@aecgeeks.com>
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

"""The geometry viewer decomposition tree must finish loading cyclic files.

``decomposition_treeview.load_file`` keeps looping while any product is neither
placed nor skipped. A product is skipped only when ``parent()`` is ``None``.
Mutual aggregates, mutual containment, a void/fill pair, a self-parent, or a
parent that is not an ``IfcProduct``/``IfcProject`` never satisfy that, so the
loop does not return. These tests open a file the way ``application.load`` does
and require the tree to return, with acyclic products placed and cyclic ones
left out.
"""

import importlib.util
import os
import signal
import sys
from pathlib import Path

import pytest

CHECKOUT = Path(__file__).resolve().parents[2]
LOAD_TIMEOUT_SECONDS = 2
SCHEMAS = ("IFC4", "IFC2X3", "IFC4X3")


def _drop_checkout_from_sys_path():
    """Import the extension module from the environment that built it.

    The checkout does not ship ``ifcopenshell_wrapper``. Pytest puts this
    source tree on ``sys.path``; leaving it there shadows the built package.
    """
    kept = []
    for entry in sys.path:
        try:
            resolved = Path(entry or os.getcwd()).resolve()
        except OSError:
            kept.append(entry)
            continue
        if resolved != CHECKOUT:
            kept.append(entry)
    sys.path[:] = kept


_drop_checkout_from_sys_path()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtCore, QtWidgets

import ifcopenshell
import ifcopenshell.guid


def _load_checkout_viewer():
    """Execute this checkout's ``geom/app.py`` inside the built package.

    Release builds replace ``version = "0.0.0"`` before the viewer is shipped
    (``conda/update_version_init.py``). The placeholder is less than ``"0.6"``,
    which makes ``app.py`` import a ``get_supertype`` symbol that is not in
    this tree. The 0.9 package reports a version that skips that branch. Use
    the built package's version, then run the checkout source so a fix to
    ``load_file`` is what these tests import.
    """
    if ifcopenshell.version == "0.0.0":
        ifcopenshell.version = "0.9.0"
    import ifcopenshell.geom as geom_pkg

    app_path = CHECKOUT / "ifcopenshell" / "geom" / "app.py"
    spec = importlib.util.spec_from_file_location("ifcopenshell.geom.app", app_path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = geom_pkg.__name__
    sys.modules["ifcopenshell.geom.app"] = module
    spec.loader.exec_module(module)
    assert Path(module.__file__).resolve() == app_path.resolve()
    return module


viewer = _load_checkout_viewer()


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _gid():
    return ifcopenshell.guid.new()


def _open_written(model, tmp_path, name):
    path = tmp_path / name
    model.write(str(path))
    return ifcopenshell.open(str(path)), path


def _project_and_site(model):
    project = model.create_entity("IfcProject", GlobalId=_gid(), Name="Project")
    site = model.create_entity("IfcSite", GlobalId=_gid(), Name="Site")
    model.create_entity(
        "IfcRelAggregates",
        GlobalId=_gid(),
        RelatingObject=project,
        RelatedObjects=[site],
    )
    return project, site


def _contained(model, structure, ifc_class, name):
    element = model.create_entity(ifc_class, GlobalId=_gid(), Name=name)
    model.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=_gid(),
        RelatingStructure=structure,
        RelatedElements=[element],
    )
    return element


def _aggregate(model, relating, related):
    model.create_entity(
        "IfcRelAggregates",
        GlobalId=_gid(),
        RelatingObject=relating,
        RelatedObjects=[related],
    )


def _returns(fn):
    def _handler(signum, frame):
        raise TimeoutError

    previous = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(LOAD_TIMEOUT_SECONDS)
    try:
        return fn()
    except TimeoutError:
        pytest.fail(f"did not return within {LOAD_TIMEOUT_SECONDS}s")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _by_name(model):
    found = {}
    for inst in list(model.by_type("IfcProduct")) + list(model.by_type("IfcProject")):
        found[inst.Name] = inst
    return found


def _new_tree():
    return viewer.application.decomposition_treeview()


def _assert_decomposition(tree, model, present, absent):
    placed = _by_name(model)
    got = {inst.Name for inst in tree.product_to_item}
    assert present <= got
    assert got.isdisjoint(absent)
    linked = {child.Name for children in tree.children.values() for child in children}
    assert present <= linked
    assert linked.isdisjoint(absent)
    for name in present:
        inst = placed[name]
        index = tree.product_to_item[inst]
        assert index.isValid()
        stored = index.data(QtCore.Qt.UserRole)
        assert stored.GlobalId == inst.GlobalId
        walked = _returns(lambda inst=inst: tree.get_children(inst))
        assert len(walked) == len({id(node) for node in walked})
        assert absent.isdisjoint({node.Name for node in walked})
    root = placed["Project"]
    assert {node.Name for node in _returns(lambda: tree.get_children(root))} == present


def test_acyclic_hierarchy_is_placed(qapp, tmp_path):
    model = ifcopenshell.file(schema="IFC4")
    _project, site = _project_and_site(model)
    _contained(model, site, "IfcWall", "Wall")
    opened, _path = _open_written(model, tmp_path, "acyclic.ifc")
    tree = _new_tree()
    _returns(lambda: tree.load_file(opened))
    _assert_decomposition(tree, opened, {"Project", "Site", "Wall"}, set())
    assert [child.Name for child in tree.children[_by_name(opened)["Project"]]] == ["Site"]
    assert [child.Name for child in tree.children[_by_name(opened)["Site"]]] == ["Wall"]


@pytest.mark.parametrize("schema", SCHEMAS)
def test_aggregate_cycle_is_skipped(qapp, tmp_path, schema):
    model = ifcopenshell.file(schema=schema)
    _project, site = _project_and_site(model)
    _contained(model, site, "IfcWall", "Good")
    left = model.create_entity("IfcWall", GlobalId=_gid(), Name="Left")
    right = model.create_entity("IfcWall", GlobalId=_gid(), Name="Right")
    _aggregate(model, left, right)
    _aggregate(model, right, left)
    opened, _path = _open_written(model, tmp_path, f"aggregate-{schema}.ifc")
    tree = _new_tree()
    _returns(lambda: tree.load_file(opened))
    _assert_decomposition(tree, opened, {"Project", "Site", "Good"}, {"Left", "Right"})


def test_self_aggregate_is_skipped(qapp, tmp_path):
    model = ifcopenshell.file(schema="IFC4")
    _project, site = _project_and_site(model)
    _contained(model, site, "IfcWall", "Good")
    loop = model.create_entity("IfcWall", GlobalId=_gid(), Name="Loop")
    _aggregate(model, loop, loop)
    opened, _path = _open_written(model, tmp_path, "self-aggregate.ifc")
    tree = _new_tree()
    _returns(lambda: tree.load_file(opened))
    _assert_decomposition(tree, opened, {"Project", "Site", "Good"}, {"Loop"})


def test_three_product_aggregate_cycle_is_skipped(qapp, tmp_path):
    model = ifcopenshell.file(schema="IFC4")
    _project, site = _project_and_site(model)
    _contained(model, site, "IfcWall", "Good")
    nodes = [model.create_entity("IfcBuildingElementProxy", GlobalId=_gid(), Name=name) for name in ("A", "B", "C")]
    _aggregate(model, nodes[0], nodes[1])
    _aggregate(model, nodes[1], nodes[2])
    _aggregate(model, nodes[2], nodes[0])
    opened, _path = _open_written(model, tmp_path, "three-cycle.ifc")
    tree = _new_tree()
    _returns(lambda: tree.load_file(opened))
    _assert_decomposition(tree, opened, {"Project", "Site", "Good"}, {"A", "B", "C"})


@pytest.mark.parametrize("schema", SCHEMAS)
def test_containment_cycle_is_skipped(qapp, tmp_path, schema):
    model = ifcopenshell.file(schema=schema)
    _project, site = _project_and_site(model)
    _contained(model, site, "IfcWall", "Good")
    left = model.create_entity("IfcWall", GlobalId=_gid(), Name="Left")
    right = model.create_entity("IfcWall", GlobalId=_gid(), Name="Right")
    model.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=_gid(),
        RelatingStructure=left,
        RelatedElements=[right],
    )
    model.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=_gid(),
        RelatingStructure=right,
        RelatedElements=[left],
    )
    opened, _path = _open_written(model, tmp_path, f"containment-{schema}.ifc")
    tree = _new_tree()
    _returns(lambda: tree.load_file(opened))
    _assert_decomposition(tree, opened, {"Project", "Site", "Good"}, {"Left", "Right"})


@pytest.mark.parametrize("schema", SCHEMAS)
def test_containment_aggregate_cycle_is_skipped(qapp, tmp_path, schema):
    model = ifcopenshell.file(schema=schema)
    _project, site = _project_and_site(model)
    _contained(model, site, "IfcWall", "Good")
    space = model.create_entity("IfcSpace", GlobalId=_gid(), Name="Space")
    wall = model.create_entity("IfcWall", GlobalId=_gid(), Name="CyclicWall")
    model.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=_gid(),
        RelatingStructure=space,
        RelatedElements=[wall],
    )
    _aggregate(model, wall, space)
    opened, _path = _open_written(model, tmp_path, f"contain-aggregate-{schema}.ifc")
    tree = _new_tree()
    _returns(lambda: tree.load_file(opened))
    _assert_decomposition(tree, opened, {"Project", "Site", "Good"}, {"Space", "CyclicWall"})


@pytest.mark.parametrize("schema", SCHEMAS)
def test_void_fill_cycle_is_skipped(qapp, tmp_path, schema):
    model = ifcopenshell.file(schema=schema)
    _project, site = _project_and_site(model)
    _contained(model, site, "IfcWall", "Good")
    wall = model.create_entity("IfcWall", GlobalId=_gid(), Name="Voided")
    opening = model.create_entity("IfcOpeningElement", GlobalId=_gid(), Name="Opening")
    model.create_entity(
        "IfcRelVoidsElement",
        GlobalId=_gid(),
        RelatingBuildingElement=wall,
        RelatedOpeningElement=opening,
    )
    model.create_entity(
        "IfcRelFillsElement",
        GlobalId=_gid(),
        RelatingOpeningElement=opening,
        RelatedBuildingElement=wall,
    )
    opened, _path = _open_written(model, tmp_path, f"void-fill-{schema}.ifc")
    tree = _new_tree()
    _returns(lambda: tree.load_file(opened))
    _assert_decomposition(tree, opened, {"Project", "Site", "Good"}, {"Voided", "Opening"})


def test_parent_outside_the_product_set_is_skipped(qapp, tmp_path):
    model = ifcopenshell.file(schema="IFC4")
    _project, site = _project_and_site(model)
    _contained(model, site, "IfcWall", "Good")
    wall = model.create_entity("IfcWall", GlobalId=_gid(), Name="Typed")
    type_object = model.create_entity("IfcTypeObject", GlobalId=_gid(), Name="Type")
    _aggregate(model, type_object, wall)
    opened, _path = _open_written(model, tmp_path, "type-parent.ifc")
    tree = _new_tree()
    _returns(lambda: tree.load_file(opened))
    _assert_decomposition(tree, opened, {"Project", "Site", "Good"}, {"Typed"})
    assert "Type" not in {inst.Name for inst in tree.product_to_item}


def test_chain_into_a_parent_outside_the_product_set_is_skipped(qapp, tmp_path):
    model = ifcopenshell.file(schema="IFC4")
    _project, site = _project_and_site(model)
    _contained(model, site, "IfcWall", "Good")
    assembly = model.create_entity("IfcElementAssembly", GlobalId=_gid(), Name="Assembly")
    wall = model.create_entity("IfcWall", GlobalId=_gid(), Name="Member")
    type_object = model.create_entity("IfcTypeObject", GlobalId=_gid(), Name="Type")
    _aggregate(model, type_object, assembly)
    _aggregate(model, assembly, wall)
    opened, _path = _open_written(model, tmp_path, "type-chain.ifc")
    tree = _new_tree()
    _returns(lambda: tree.load_file(opened))
    _assert_decomposition(tree, opened, {"Project", "Site", "Good"}, {"Assembly", "Member"})


def test_application_load_opens_a_cyclic_file(qapp, tmp_path):
    model = ifcopenshell.file(schema="IFC4")
    _project, site = _project_and_site(model)
    _contained(model, site, "IfcWall", "Good")
    left = model.create_entity("IfcWall", GlobalId=_gid(), Name="Left")
    right = model.create_entity("IfcWall", GlobalId=_gid(), Name="Right")
    _aggregate(model, left, right)
    _aggregate(model, right, left)
    _opened, path = _open_written(model, tmp_path, "opened.ifc")
    tree = _new_tree()
    types = viewer.application.type_treeview()

    class _Host:
        def __init__(self):
            self.files = {}
            self.components = [tree, types]
            self.settings = None

    host = _Host()
    _returns(lambda: viewer.application.load(host, str(path)))
    opened = host.files[str(path)]
    _assert_decomposition(tree, opened, {"Project", "Site", "Good"}, {"Left", "Right"})
    placed = _by_name(opened)
    assert placed["Left"] in types.product_to_item
    assert placed["Good"] in types.product_to_item
    assert [node.Name for node in _returns(lambda: types.get_children(placed["Good"]))] == ["Good"]
