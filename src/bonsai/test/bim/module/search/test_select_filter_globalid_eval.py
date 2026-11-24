# This file was generated with the assistance of an AI coding tool.
"""GlobalIds from an IFC file must not be executed by Select Filter Elements.

The eyedropper (``bim.select_filter_elements``) builds a query from the
GlobalIds of the selected elements. For 50 or fewer elements that query is
the raw GlobalId text. If it starts with ``bpy.data.texts['`` the operator
passes it to ``eval``. These tests open a STEP file, link the parsed elements
the way the importer does, and invoke the real operator. They fail while that
``eval`` still runs the GlobalId, and pass once it no longer does.

``ExtractSelectedElements`` (``bim.patch_query_from_selected``) copies the same
query into a patch argument and does not evaluate it, so it is not a second
sink and is not covered here. The eyedropper button in ``bim/helper.py`` only
sets ``group_index``, ``index`` and ``module``; those are the values passed
into ``SelectFilterElements.execute``.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path

import pytest

BONSAI_ROOT = Path(__file__).resolve().parents[4]
PROBE_NAME = "bonsai_globalid_eval_probe"

# Same operator, different panels. drawing and clash property accessors are
# the attribute reads in tool/drawing.py and tool/clash.py; those modules are
# not imported whole because they require Blender and ifcclash. They do not
# interpret GlobalIds. Search.get_filter_groups and SelectFilterElements are
# the real functions.
MODULES = ("search", "csv", "diff", "drawing_include", "drawing_exclude", "clash_0_a_0")


class _Probe:
    calls: list[str] = []

    @staticmethod
    def hit(token: str) -> str:
        _Probe.calls.append(token)
        return token


def _text_block_payload(token: str) -> str:
    # Empty-string subscript so the key expression runs before the lookup.
    return f"bpy.data.texts[''+str(__import__(\"{PROBE_NAME}\").hit(\"{token}\"))]"


def _prefixed_text_block_payload(token: str) -> str:
    # Still a key expression, and the literal text also contains the prefix
    # Bonsai uses for its own text blocks.
    return (
        "bpy.data.texts['globalid-filter-'+str(__import__(\""
        + PROBE_NAME
        + f"\").hit(\"{token}\"))]"
    )


def _spf_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _write_ifc(global_ids: list[str]) -> Path:
    entities = []
    for index, global_id in enumerate(global_ids, start=1):
        entities.append(f"#{index}=IFCWALL({_spf_quote(global_id)},$,'Wall',$,$,$,$,$,$);")
    body = "\n".join(
        [
            "ISO-10303-21;",
            "HEADER;",
            "FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');",
            "FILE_NAME('','2024-01-01T00:00:00',(''),(''),'','','');",
            "FILE_SCHEMA(('IFC4'));",
            "ENDSEC;",
            "DATA;",
            *entities,
            "ENDSEC;",
            "END-ISO-10303-21;",
            "",
        ]
    )
    descriptor, name = tempfile.mkstemp(suffix=".ifc")
    os.close(descriptor)
    path = Path(name)
    path.write_text(body, encoding="ascii")
    return path


def _ensure_package(name: str, path: Path | None = None) -> types.ModuleType:
    if name in sys.modules:
        module = sys.modules[name]
    else:
        module = types.ModuleType(name)
        module.__package__ = name.rpartition(".")[0]
        module.__path__ = [str(path)] if path else []
        module.__file__ = str(path / "__init__.py") if path else "<test-stub>"
        sys.modules[name] = module
    parent, _, child = name.rpartition(".")
    if parent and parent in sys.modules:
        setattr(sys.modules[parent], child, module)
    return module


def _load(modname: str, path: Path):
    spec = importlib.util.spec_from_file_location(modname, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[modname] = module
    parent, _, child = modname.rpartition(".")
    if parent and parent in sys.modules:
        setattr(sys.modules[parent], child, module)
    spec.loader.exec_module(module)
    return module


class _Types(types.ModuleType):
    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        cls = type(name, (), {})
        setattr(self, name, cls)
        return cls


class _Texts(dict):
    def new(self, name: str):
        text = types.SimpleNamespace(name=name, body="")
        text.from_string = lambda value, _text=text: setattr(_text, "body", value)
        text.as_string = lambda _text=text: _text.body
        text.write = lambda value, _text=text: setattr(_text, "body", _text.body + value)
        self[name] = text
        return text


def _install_bpy_stub():
    if "bpy" in sys.modules and hasattr(sys.modules["bpy"], "types"):
        return sys.modules["bpy"]
    bpy = _ensure_package("bpy")
    props = _ensure_package("bpy.props")
    for prop_name in (
        "BoolProperty",
        "CollectionProperty",
        "EnumProperty",
        "FloatProperty",
        "FloatVectorProperty",
        "IntProperty",
        "PointerProperty",
        "StringProperty",
    ):
        setattr(props, prop_name, lambda *args, **kwargs: None)
    bpy.types = _Types("bpy.types")
    sys.modules["bpy.types"] = bpy.types
    bpy.types.Operator = type("Operator", (), {})
    bpy.data = types.SimpleNamespace(
        texts=_Texts(),
        objects=types.SimpleNamespace(get=lambda name: None),
        materials=types.SimpleNamespace(get=lambda name: None),
    )
    bpy.context = types.SimpleNamespace(
        scene=types.SimpleNamespace(),
        selected_objects=[],
        area=None,
        space_data=None,
    )
    bpy.app = types.SimpleNamespace(
        background=True,
        version=(4, 2, 0),
        handlers=types.SimpleNamespace(persistent=lambda func: func),
    )
    bpy.utils = _ensure_package("bpy.utils")
    bpy.msgbus = types.SimpleNamespace(
        clear_by_owner=lambda *args, **kwargs: None,
        subscribe_rna=lambda *args, **kwargs: None,
    )
    return bpy


def _install_mathutils_stub():
    if "mathutils" in sys.modules:
        return
    mathutils = _ensure_package("mathutils")

    class Vector(tuple):
        def __new__(cls, data=()):
            return tuple.__new__(cls, tuple(data))

    mathutils.Vector = Vector
    mathutils.Matrix = type("Matrix", (), {})
    mathutils.Euler = type("Euler", (), {})
    mathutils.Color = type("Color", (), {})


def _load_product():
    if getattr(_load_product, "ready", False):
        return
    _install_mathutils_stub()
    for name in ("bmesh", "gpu", "gpu_extras", "gpu_extras.batch", "bpy_extras", "bpy_extras.io_utils"):
        _ensure_package(name)
    sys.modules["gpu_extras.batch"].batch_for_shader = lambda *args, **kwargs: None
    _install_bpy_stub()

    bonsai_pkg = BONSAI_ROOT / "bonsai"
    _ensure_package("bonsai", bonsai_pkg)
    _ensure_package("bonsai.bim", bonsai_pkg / "bim")
    _ensure_package("bonsai.bim.module", bonsai_pkg / "bim" / "module")
    _ensure_package("bonsai.bim.module.search", bonsai_pkg / "bim" / "module" / "search")
    _ensure_package("bonsai.core", bonsai_pkg / "core")
    _ensure_package("bonsai.tool", bonsai_pkg / "tool")
    if str(BONSAI_ROOT) not in sys.path:
        sys.path.insert(0, str(BONSAI_ROOT))

    handler = _ensure_package("bonsai.bim.handler")
    handler.object_subscription_owner = object()
    handler.subscribe_to = lambda *args, **kwargs: None
    handler.active_material_index_callback = None
    handler.name_callback = None
    schema = _ensure_package("bonsai.bim.schema")
    schema.reload = lambda *args, **kwargs: None
    brick = _ensure_package("bonsai.tool.brick")
    brick.BrickStore = type("BrickStore", (), {})

    _load("bonsai.core.tool", bonsai_pkg / "core" / "tool.py")
    _load("bonsai.core.search", bonsai_pkg / "core" / "search.py")
    _load("bonsai.bim.ifc", bonsai_pkg / "bim" / "ifc.py")
    ifc_mod = _load("bonsai.tool.ifc", bonsai_pkg / "tool" / "ifc.py")
    blender_mod = _load("bonsai.tool.blender", bonsai_pkg / "tool" / "blender.py")
    tool = sys.modules["bonsai.tool"]
    tool.Blender = blender_mod.Blender
    tool.Ifc = ifc_mod.Ifc
    _load("bonsai.bim.prop", bonsai_pkg / "bim" / "prop.py")
    _load("bonsai.tool.search", bonsai_pkg / "tool" / "search.py")
    _load("bonsai.bim.module.search.operator", bonsai_pkg / "bim" / "module" / "search" / "operator.py")
    tool.Search = sys.modules["bonsai.tool.search"].Search

    # Accessors copied from the functions that only read Blender properties.
    # tool/drawing.py get_camera_props, tool/clash.py get_clash_props.
    bpy = sys.modules["bpy"]

    class Drawing:
        @classmethod
        def get_camera_props(cls, camera):
            if isinstance(camera, bpy.types.Camera):
                data = camera
            else:
                assert isinstance(data := camera.data, bpy.types.Camera)
            return data.BIMCameraProperties

    class Clash:
        @classmethod
        def get_clash_props(cls):
            return bpy.context.scene.BIMClashProperties

    tool.Drawing = Drawing
    tool.Clash = Clash

    probe = types.ModuleType(PROBE_NAME)
    probe.hit = _Probe.hit
    sys.modules[PROBE_NAME] = probe
    _load_product.ready = True


def _reset_runtime():
    _load_product()
    _Probe.calls = []
    bpy = sys.modules["bpy"]
    bpy.data.texts.clear()
    bpy.context.selected_objects = []
    bpy.context.scene = types.SimpleNamespace()
    from bonsai.bim.ifc import IfcStore

    IfcStore.file = None
    IfcStore.id_map = {}
    IfcStore.guid_map = {}
    IfcStore.history = []


def _open_walls(global_ids: list[str]):
    import ifcopenshell

    path = _write_ifc(global_ids)
    ifc_file = ifcopenshell.open(str(path))
    path.unlink()
    by_guid = {element.GlobalId: element for element in ifc_file.by_type("IfcWall")}
    missing = [global_id for global_id in global_ids if global_id not in by_guid]
    assert not missing, missing
    return ifc_file, [by_guid[global_id] for global_id in global_ids]


def _select(ifc_file, elements):
    from bonsai.bim.ifc import IfcStore

    bpy = sys.modules["bpy"]
    IfcStore.file = ifc_file
    tool = sys.modules["bonsai.tool"]
    selected = []
    for element in elements:
        obj = bpy.types.Object()
        obj.BIMObjectProperties = types.SimpleNamespace(ifc_definition_id=0)
        tool.Ifc.link(element, obj)
        assert obj.BIMObjectProperties.ifc_definition_id == element.id()
        selected.append(obj)
    bpy.context.selected_objects = selected


def _install_filter_group(module: str):
    bpy = sys.modules["bpy"]
    filt = types.SimpleNamespace(value="")
    group = types.SimpleNamespace(filters=[filt])
    groups = [group]
    scene = bpy.context.scene
    if module == "search":
        scene.BIMSearchProperties = types.SimpleNamespace(filter_groups=groups)
    elif module == "csv":
        scene.CsvProperties = types.SimpleNamespace(filter_groups=groups)
    elif module == "diff":
        scene.DiffProperties = types.SimpleNamespace(filter_groups=groups)
    elif module in ("drawing_include", "drawing_exclude"):
        camera_data = bpy.types.Camera()
        camera_data.BIMCameraProperties = types.SimpleNamespace(
            include_filter_groups=groups,
            exclude_filter_groups=groups,
        )
        camera = bpy.types.Object()
        camera.data = camera_data
        scene.camera = camera
    elif module.startswith("clash"):
        source = types.SimpleNamespace(filter_groups=groups)
        scene.BIMClashProperties = types.SimpleNamespace(
            clash_sets=[types.SimpleNamespace(a=[source], b=[source])]
        )
    else:
        raise AssertionError(module)
    return filt


def _run_eyedropper(module: str):
    operator_cls = sys.modules["bonsai.bim.module.search.operator"].SelectFilterElements
    operator = operator_cls.__new__(operator_cls)
    operator.group_index = 0
    operator.index = 0
    operator.module = module
    operator.report = lambda *args, **kwargs: None
    try:
        return operator.execute(sys.modules["bpy"].context), None
    except Exception as exc:  # the vulnerable path raises after the payload runs
        return None, exc


@pytest.fixture(autouse=True)
def _runtime():
    _reset_runtime()
    yield


@pytest.mark.parametrize("module", MODULES)
def test_parsed_globalid_is_not_evaluated(module):
    payload = _text_block_payload("wall")
    ifc_file, elements = _open_walls([payload])
    assert elements[0].GlobalId == payload
    _select(ifc_file, elements)
    _install_filter_group(module)

    result, exc = _run_eyedropper(module)

    assert _Probe.calls == [], (module, _Probe.calls, exc)
    assert exc is None
    assert result == {"FINISHED"}


def test_generated_text_block_prefix_is_not_a_reason_to_evaluate():
    payload = _prefixed_text_block_payload("prefixed")
    ifc_file, elements = _open_walls([payload])
    assert elements[0].GlobalId == payload
    _select(ifc_file, elements)
    _install_filter_group("search")

    result, exc = _run_eyedropper("search")

    assert _Probe.calls == [], (_Probe.calls, exc)
    assert exc is None
    assert result == {"FINISHED"}


def test_joined_payload_globalids_are_not_evaluated():
    first = _text_block_payload("first")
    second = _text_block_payload("second")
    ifc_file, elements = _open_walls([first, second])
    _select(ifc_file, elements)
    _install_filter_group("search")

    result, exc = _run_eyedropper("search")

    assert _Probe.calls == [], (_Probe.calls, exc)
    assert exc is None
    assert result == {"FINISHED"}


def test_plain_globalid_is_stored_verbatim():
    import ifcopenshell

    global_id = ifcopenshell.guid.new()
    ifc_file, elements = _open_walls([global_id])
    assert elements[0].GlobalId == global_id
    _select(ifc_file, elements)
    filt = _install_filter_group("search")

    result, exc = _run_eyedropper("search")

    assert exc is None
    assert result == {"FINISHED"}
    assert filt.value == global_id
    assert _Probe.calls == []


def test_expression_without_text_block_prefix_is_not_evaluated():
    payload = f'__import__("{PROBE_NAME}").hit("bare")'
    ifc_file, elements = _open_walls([payload])
    assert elements[0].GlobalId == payload
    _select(ifc_file, elements)
    filt = _install_filter_group("search")

    result, exc = _run_eyedropper("search")

    assert exc is None
    assert result == {"FINISHED"}
    assert filt.value == payload
    assert _Probe.calls == []


def test_more_than_fifty_globalids_stay_data_in_a_generated_text_block():
    import ifcopenshell

    payload = _text_block_payload("among-many")
    global_ids = [ifcopenshell.guid.new() for _ in range(50)]
    global_ids.append(payload)
    ifc_file, elements = _open_walls(global_ids)
    _select(ifc_file, elements)
    filt = _install_filter_group("search")

    result, exc = _run_eyedropper("search")

    assert _Probe.calls == [], (_Probe.calls, exc)
    assert exc is None
    assert result == {"FINISHED"}
    assert filt.value.startswith("bpy.data.texts['globalid-filter-")
    assert filt.value.endswith("']")
    name = filt.value[len("bpy.data.texts['") : -2]
    stored = sys.modules["bpy"].data.texts[name].as_string()
    for global_id in global_ids:
        assert global_id in stored
