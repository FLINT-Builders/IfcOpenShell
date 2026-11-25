# This file was generated with the assistance of an AI coding tool.
"""glTF export must not read past the triangle index buffer.

A Body representation that contains both a solid and a curve produces one mesh
whose material id list counts every triangle and every curve segment. The glTF
writer advances through the triangle indices by three entries per material id.
These tests run IfcConvert on that input.

They pass only when conversion exits 0, AddressSanitizer stays silent, and the
TRIANGLES primitives do not absorb the curve segments. They fail while the
writer still reads past the face buffer.

Run against an AddressSanitizer build of this tree (schema IFC4, GLTF_SUPPORT):

    cmake -S cmake -B /tmp/ifcos-build -G Ninja \\
        -DCMAKE_C_COMPILER=/usr/bin/gcc -DCMAKE_CXX_COMPILER=/usr/bin/g++ \\
        -DCMAKE_BUILD_TYPE=RelWithDebInfo \\
        -DCMAKE_CXX_FLAGS="-fsanitize=address,undefined -fno-omit-frame-pointer -g -O1" \\
        -DCMAKE_C_FLAGS="-fsanitize=address,undefined -fno-omit-frame-pointer -g -O1" \\
        -DCMAKE_EXE_LINKER_FLAGS="-fsanitize=address,undefined" \\
        -DCMAKE_SHARED_LINKER_FLAGS="-fsanitize=address,undefined" \\
        -DSCHEMA_VERSIONS=4 -DGLTF_SUPPORT=ON -DWITH_CGAL=OFF \\
        -DWITH_OPENCASCADE=ON -DBUILD_IFCPYTHON=OFF -DBUILD_GEOMSERVER=OFF \\
        -DBUILD_EXAMPLES=OFF -DCOLLADA_SUPPORT=OFF -DBUILD_CONVERT=ON
    cmake --build /tmp/ifcos-build --target IfcConvert -j 8
    python3 src/ifcconvert/tests/test_gltf_mixed_curve_solid.py \\
        --ifcconvert /tmp/ifcos-build/ifcconvert/IfcConvert
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

# A rectangular extrusion is a handful of triangles. The curve below has
# thousands of segments; absorbing those material ids as triangles makes the
# index count far larger than this bound.
MAX_TRIANGLE_INDICES = 300
CURVE_SEGMENTS = 4000
GLB_MAGIC = b"glTF"
PRIM_TRIANGLES = 4
ASAN_NEEDLE = "AddressSanitizer"


def _id(n: int) -> str:
    return f"{n:022d}"[:22]


def _point(coords: tuple[float, ...]) -> str:
    body = ",".join(f"{c:.6f}" for c in coords)
    return f"IFCCARTESIANPOINT(({body}))"


def write_ifc(path: Path, *, solid: bool, curve_segments: int) -> None:
    """IFC4 wall whose Body holds an extrusion, a polyline, or both."""
    entities: list[str] = []

    def add(body: str) -> int:
        entities.append(body)
        return len(entities)

    person = add("IFCPERSON($,'Tester',$,$,$,$,$,$)")
    org = add("IFCORGANIZATION($,'Test',$,$,$)")
    pao = add(f"IFCPERSONANDORGANIZATION(#{person},#{org},$)")
    app = add(f"IFCAPPLICATION(#{org},'0.9','test','test')")
    owner = add(
        f"IFCOWNERHISTORY(#{pao},#{app},.READWRITE.,.ADDED.,1,#{pao},#{app},1)"
    )
    origin = add(_point((0.0, 0.0, 0.0)))
    up = add("IFCDIRECTION((0.,0.,1.))")
    xdir = add("IFCDIRECTION((1.,0.,0.))")
    axis = add(f"IFCAXIS2PLACEMENT3D(#{origin},#{up},#{xdir})")
    context = add(f"IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#{axis},$)")
    body_ctx = add(
        f"IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,#{context},$,.MODEL_VIEW.,$)"
    )
    unit = add("IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.)")
    units = add(f"IFCUNITASSIGNMENT((#{unit}))")
    add(
        f"IFCPROJECT('{_id(1)}',#{owner},'P',$,$,$,$,(#{context}),#{units})"
    )

    items: list[int] = []
    if solid:
        p0 = add(_point((0.0, 0.0)))
        p1 = add(_point((1.0, 0.0)))
        p2 = add(_point((1.0, 0.2)))
        p3 = add(_point((0.0, 0.2)))
        profile_curve = add(f"IFCPOLYLINE((#{p0},#{p1},#{p2},#{p3},#{p0}))")
        profile = add(f"IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,#{profile_curve})")
        position = add(f"IFCAXIS2PLACEMENT3D(#{origin},#{up},#{xdir})")
        direction = add("IFCDIRECTION((0.,0.,1.))")
        items.append(
            add(f"IFCEXTRUDEDAREASOLID(#{profile},#{position},#{direction},2.)")
        )
    if curve_segments:
        # Open polyline. Spaced well above the default precision so points survive
        # duplicate removal and become one edge per segment.
        point_ids = [
            add(_point((i * 0.05, 5.0, 0.0))) for i in range(curve_segments + 1)
        ]
        refs = ",".join(f"#{pid}" for pid in point_ids)
        items.append(add(f"IFCPOLYLINE(({refs}))"))

    item_refs = ",".join(f"#{i}" for i in items)
    shape = add(
        f"IFCSHAPEREPRESENTATION(#{body_ctx},'Body','SweptSolid',({item_refs}))"
    )
    definition = add(f"IFCPRODUCTDEFINITIONSHAPE($,$,(#{shape}))")
    placement = add(f"IFCLOCALPLACEMENT($,#{axis})")
    add(
        f"IFCWALL('{_id(2)}',#{owner},'Wall',$,$,#{placement},#{definition},$,$)"
    )

    lines = [
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');",
        "FILE_NAME('mixed.ifc','2026-01-01T00:00:00',(''),(''),'','','');",
        "FILE_SCHEMA(('IFC4'));",
        "ENDSEC;",
        "DATA;",
    ]
    for index, body in enumerate(entities, start=1):
        lines.append(f"#{index}={body};")
    lines.append("ENDSEC;")
    lines.append("END-ISO-10303-21;")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def _library_path(ifcconvert: Path) -> str:
    build = ifcconvert.resolve().parent.parent
    dirs = [
        build / "ifcconvert",
        build / "ifcgeom",
        build / "ifcparse",
        build / "serializers",
        build / "plugin",
    ]
    extra = [str(d) for d in dirs if d.is_dir()]
    current = os.environ.get("LD_LIBRARY_PATH", "")
    return os.pathsep.join(extra + ([current] if current else []))


def convert(ifcconvert: Path, ifc: Path, glb: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = _library_path(ifcconvert)
    env["ASAN_OPTIONS"] = "halt_on_error=1:abort_on_error=1:detect_leaks=0:symbolize=1"
    env["UBSAN_OPTIONS"] = "halt_on_error=1:abort_on_error=1:print_stacktrace=1"
    command = [
        str(ifcconvert),
        "--yes",
        "--no-progress",
        "--quiet",
        "--threads",
        "1",
        "--kernel",
        "opencascade",
        *args,
        str(ifc),
        str(glb),
    ]
    return subprocess.run(
        command,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
    )


def triangle_index_count(glb: Path) -> int:
    data = glb.read_bytes()
    if len(data) < 20 or data[:4] != GLB_MAGIC:
        raise AssertionError(f"{glb} is not a glb (size {len(data)})")
    offset = 12
    json_text = None
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8 : offset + 8 + length]
        offset += 8 + length
        if kind == 0x4E4F534A:
            json_text = chunk.rstrip(b" \x00").decode("utf-8")
            break
    if json_text is None:
        raise AssertionError(f"{glb} has no JSON chunk")
    document = json.loads(json_text)
    accessors = document.get("accessors", [])
    total = 0
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            mode = primitive.get("mode", PRIM_TRIANGLES)
            if mode != PRIM_TRIANGLES:
                continue
            index = primitive.get("indices")
            if index is None:
                continue
            total += int(accessors[index]["count"])
    return total


def _fail(name: str, message: str, result: subprocess.CompletedProcess[str] | None = None) -> None:
    print(f"FAIL {name}: {message}", file=sys.stderr)
    if result is not None:
        tail = (result.stderr or "")[-4000:]
        if tail:
            print(tail, file=sys.stderr)
    raise SystemExit(1)


def expect_clean(
    name: str,
    ifcconvert: Path,
    *,
    solid: bool,
    curve_segments: int,
    args: list[str],
    require_triangles: bool,
) -> None:
    with tempfile.TemporaryDirectory(prefix="gltf-mat-") as tmp:
        root = Path(tmp)
        ifc = root / "input.ifc"
        glb = root / "output.glb"
        write_ifc(ifc, solid=solid, curve_segments=curve_segments)
        result = convert(ifcconvert, ifc, glb, args)
        combined = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0 or ASAN_NEEDLE in combined:
            _fail(name, f"conversion failed with status {result.returncode}", result)
        if not glb.is_file():
            _fail(name, "IfcConvert exited 0 without writing a glb", result)
        count = triangle_index_count(glb)
        if count > MAX_TRIANGLE_INDICES:
            _fail(
                name,
                f"TRIANGLES index count {count} exceeds {MAX_TRIANGLE_INDICES}; "
                "curve material ids were consumed as triangle indices",
                result,
            )
        if require_triangles and count == 0:
            _fail(name, "solid produced no triangle indices", result)
        print(f"PASS {name}: triangle indices={count}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ifcconvert", required=True, type=Path)
    args = parser.parse_args()
    ifcconvert = args.ifcconvert
    if not ifcconvert.is_file():
        _fail("setup", f"IfcConvert not found at {ifcconvert}")

    # Controls that already succeed: the solid alone, the curve alone, and the
    # mixed file when curves are left out of the mesh.
    expect_clean(
        "solid-only-plan-model",
        ifcconvert,
        solid=True,
        curve_segments=0,
        args=["--plan", "--model"],
        require_triangles=True,
    )
    expect_clean(
        "curve-only-plan",
        ifcconvert,
        solid=False,
        curve_segments=CURVE_SEGMENTS,
        args=["--plan"],
        require_triangles=False,
    )
    expect_clean(
        "mixed-surfaces-and-solids",
        ifcconvert,
        solid=True,
        curve_segments=CURVE_SEGMENTS,
        args=["--dimensionality", "SURFACES_AND_SOLIDS"],
        require_triangles=True,
    )
    # The reported path. Both flags select CURVES_SURFACES_AND_SOLIDS, which
    # keeps the polyline in the same mesh as the extrusion.
    expect_clean(
        "mixed-plan-model",
        ifcconvert,
        solid=True,
        curve_segments=CURVE_SEGMENTS,
        args=["--plan", "--model"],
        require_triangles=False,
    )
    expect_clean(
        "mixed-dimensionality",
        ifcconvert,
        solid=True,
        curve_segments=CURVE_SEGMENTS,
        args=["--dimensionality", "CURVES_SURFACES_AND_SOLIDS"],
        require_triangles=False,
    )


if __name__ == "__main__":
    main()
