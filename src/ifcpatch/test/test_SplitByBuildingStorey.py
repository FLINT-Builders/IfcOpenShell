# This file was generated with the assistance of an AI coding tool.
# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2022 Dion Moult <dion@thinkmoult.com>
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

import builtins
import os
import subprocess
import sys
from pathlib import Path

import ifcopenshell
import pytest

import ifcpatch

# Characters that are path separators or reserved in a Windows filename.
# A storey name is attacker-controlled IFC data and must not survive into a
# path component that open() will interpret.
_UNSAFE_FILENAME_CHARS = set("/\\:\0")
_SENTINEL = b"ORIGINAL-SENTINEL-NOT-IFC\n"


def _escaping_storey_name(output_dir: Path, outside_file: Path, prefix: str = "") -> str:
    """Storey name that, once prefixed with ``{index}-``, walks out of output_dir.

    The recipe builds ``{index}-{name}.ifc``. With an empty prefix the first
    directory component is ``0-``; otherwise it is ``0-{prefix}``. ``..`` is
    kept so the joined path leaves output_dir when that directory exists.
    """
    anchor = output_dir / f"0-{prefix}"
    relative = Path(os.path.relpath(outside_file.with_suffix(""), anchor))
    tail = "/".join(relative.parts)
    return f"{prefix}/{tail}" if prefix else f"/{tail}"


def _model_with_storeys(names: list[str | None]) -> ifcopenshell.file:
    """Build a model, write it, and reopen it so names come back through the parser."""
    model = ifcopenshell.file(schema="IFC4")
    for name in names:
        kwargs = {"GlobalId": ifcopenshell.guid.new()}
        if name is not None:
            kwargs["Name"] = name
        model.create_entity("IfcBuildingStorey", **kwargs)
    disk = Path(os.environ.get("TMPDIR", "/tmp")) / f"storey-roundtrip-{os.getpid()}.ifc"
    try:
        model.write(disk)
        return ifcopenshell.open(disk)
    finally:
        disk.unlink(missing_ok=True)


def _run(model: ifcopenshell.file, output_dir: str | None) -> None:
    args: dict = {"file": model, "recipe": "SplitByBuildingStorey"}
    if output_dir is not None:
        args["arguments"] = [output_dir]
    ifcpatch.execute(args)


def _snapshot_outside(root: Path, output_dir: Path) -> dict[str, bytes]:
    """Bytes of every non-directory under root that is not inside output_dir.

    Symlinks are recorded as their target text and are not followed, so a
    write through a directory symlink shows up as a new file at the target.
    """
    output_resolved = output_dir.resolve()
    found: dict[str, bytes] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        kept = []
        for dirname in dirnames:
            child = current / dirname
            if child.is_symlink():
                found[str(child)] = b"SYMLINK:" + os.readlink(child).encode()
                continue
            try:
                if child.resolve() == output_resolved:
                    continue
            except OSError:
                pass
            kept.append(dirname)
        dirnames[:] = kept
        for filename in filenames:
            path = current / filename
            if path.is_symlink():
                found[str(path)] = b"SYMLINK:" + os.readlink(path).encode()
            else:
                found[str(path)] = path.read_bytes()
    return found


def _assert_safe_split(
    root: Path,
    output_dir: Path,
    before: dict[str, bytes],
    storey_count: int,
    ignore_outside: tuple[Path, ...] = (),
) -> None:
    after = _snapshot_outside(root, output_dir)
    for ignored in ignore_outside:
        after.pop(str(ignored), None)
    assert after == before, "split wrote or replaced a file outside the output directory"
    direct = [path for path in output_dir.iterdir() if path.is_file() and not path.is_symlink()]
    ifc_files = [path for path in direct if path.suffix == ".ifc"]
    assert len(ifc_files) == storey_count
    output_resolved = output_dir.resolve()
    for path in ifc_files:
        # Re-resolve at assertion time so a path that was checked earlier and
        # then swapped for a symlink is judged by where the bytes landed.
        resolved = path.resolve()
        assert output_resolved == resolved or output_resolved in resolved.parents
        assert path.parent == output_dir
        assert not any(part == ".." for part in path.parts)
        assert not _UNSAFE_FILENAME_CHARS.intersection(path.name)
        reopened = ifcopenshell.open(path)
        assert len(reopened.by_type("IfcBuildingStorey")) == storey_count


class TestSplitByBuildingStoreyPath:
    def test_dotdot_does_not_overwrite_file_outside_output_dir(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "work" / "split"
        output_dir.mkdir(parents=True)
        # The recipe prefixes the storey name with "{index}-", so the first
        # path component of "0-/../../../outside/federated.ifc" is a real
        # directory the victim already has. Linux will then walk "..".
        (output_dir / "0-").mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        sentinel = outside / "federated.ifc"
        sentinel.write_bytes(_SENTINEL)
        before = _snapshot_outside(tmp_path, output_dir)

        model = _model_with_storeys([_escaping_storey_name(output_dir, sentinel)])
        _run(model, str(output_dir))

        _assert_safe_split(tmp_path, output_dir, before, storey_count=1)
        assert sentinel.read_bytes() == _SENTINEL

    def test_dotdot_does_not_create_missing_parents_outside_output_dir(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "work" / "split"
        output_dir.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        sentinel = outside / "federated.ifc"
        before = _snapshot_outside(tmp_path, output_dir)

        model = _model_with_storeys([_escaping_storey_name(output_dir, sentinel)])
        _run(model, str(output_dir))

        _assert_safe_split(tmp_path, output_dir, before, storey_count=1)
        assert not sentinel.exists()
        assert not (output_dir / "0-").exists()

    def test_storey_name_with_interior_separators_stays_inside(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "work" / "split"
        output_dir.mkdir(parents=True)
        # First component is "0-Level", not "0-". Sanitizing only a leading slash is not enough.
        (output_dir / "0-Level").mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        sentinel = outside / "federated.ifc"
        sentinel.write_bytes(_SENTINEL)
        before = _snapshot_outside(tmp_path, output_dir)

        model = _model_with_storeys([_escaping_storey_name(output_dir, sentinel, prefix="Level")])
        _run(model, str(output_dir))

        _assert_safe_split(tmp_path, output_dir, before, storey_count=1)
        assert sentinel.read_bytes() == _SENTINEL

    def test_backslash_is_not_kept_in_the_output_filename(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "work" / "split"
        output_dir.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        before = _snapshot_outside(tmp_path, output_dir)

        model = _model_with_storeys(["..\\..\\..\\outside\\federated"])
        _run(model, str(output_dir))

        _assert_safe_split(tmp_path, output_dir, before, storey_count=1)

    def test_directory_symlink_is_not_a_way_out_of_output_dir(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "work" / "split"
        output_dir.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        sentinel = outside / "secret.ifc"
        (output_dir / "0-").symlink_to(outside, target_is_directory=True)
        before = _snapshot_outside(tmp_path, output_dir)

        model = _model_with_storeys(["/secret"])
        _run(model, str(output_dir))

        _assert_safe_split(tmp_path, output_dir, before, storey_count=1)
        assert not sentinel.exists()

    def test_symlink_retargeted_between_check_and_write_is_not_followed(self, tmp_path: Path) -> None:
        """A containment check that opens the original path again must not follow a swapped symlink.

        The link starts inside the output directory, so a resolve() check passes.
        The first open of a path that still contains the link retargets it
        outside before that open proceeds. copyfile(), ifcopenshell.open(), and
        file.write() each open the destination separately.
        """
        output_dir = tmp_path / "work" / "split"
        output_dir.mkdir(parents=True)
        inside = output_dir / "inside"
        inside.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        link = output_dir / "0-"
        link.symlink_to(inside, target_is_directory=True)
        before = _snapshot_outside(tmp_path, output_dir)
        real_open = builtins.open
        state = {"flipped": False}

        def flipping_open(file, *args, **kwargs):
            if not state["flipped"]:
                try:
                    parts = Path(os.fspath(file)).parts
                except (TypeError, ValueError):
                    parts = ()
                if "0-" in parts:
                    link.unlink()
                    link.symlink_to(outside, target_is_directory=True)
                    state["flipped"] = True
            return real_open(file, *args, **kwargs)

        model = _model_with_storeys(["/secret"])
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(builtins, "open", flipping_open)
            _run(model, str(output_dir))

        _assert_safe_split(tmp_path, output_dir, before, storey_count=1)
        assert not (outside / "secret.ifc").exists()
        assert not any(path.name == "secret.ifc" for path in outside.rglob("*"))

    def test_omitted_output_dir_uses_cwd_and_still_stays_inside(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output_dir = tmp_path / "cwd-output"
        output_dir.mkdir()
        (output_dir / "0-").mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        sentinel = outside / "federated.ifc"
        sentinel.write_bytes(_SENTINEL)
        before = _snapshot_outside(tmp_path, output_dir)
        monkeypatch.chdir(output_dir)

        model = _model_with_storeys([_escaping_storey_name(output_dir, sentinel)])
        _run(model, None)

        _assert_safe_split(tmp_path, output_dir, before, storey_count=1)
        assert sentinel.read_bytes() == _SENTINEL

    def test_each_storey_is_contained(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "work" / "split"
        output_dir.mkdir(parents=True)
        (output_dir / "0-").mkdir()
        (output_dir / "1-Level").mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        first = outside / "federated.ifc"
        second = outside / "other.ifc"
        first.write_bytes(_SENTINEL)
        second.write_bytes(_SENTINEL)
        before = _snapshot_outside(tmp_path, output_dir)

        model = _model_with_storeys(
            [
                _escaping_storey_name(output_dir, first),
                _escaping_storey_name(output_dir, second, prefix="Level"),
            ]
        )
        _run(model, str(output_dir))

        _assert_safe_split(tmp_path, output_dir, before, storey_count=2)
        assert first.read_bytes() == _SENTINEL
        assert second.read_bytes() == _SENTINEL

    def test_benign_storey_name_is_a_single_file_in_the_output_dir(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "work" / "split"
        output_dir.mkdir(parents=True)
        before = _snapshot_outside(tmp_path, output_dir)

        model = _model_with_storeys(["Level 1"])
        _run(model, str(output_dir))

        _assert_safe_split(tmp_path, output_dir, before, storey_count=1)
        assert (output_dir / "0-Level 1.ifc").is_file()

    def test_cli_does_not_write_outside_the_argument_directory(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "work" / "split"
        output_dir.mkdir(parents=True)
        (output_dir / "0-").mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        sentinel = outside / "federated.ifc"
        sentinel.write_bytes(_SENTINEL)
        source = tmp_path / "input.ifc"
        _model_with_storeys([_escaping_storey_name(output_dir, sentinel)]).write(source)
        cli_output = tmp_path / "cli-output.ifc"
        before = _snapshot_outside(tmp_path, output_dir)
        env = os.environ.copy()
        repo_pkg = str(Path(ifcpatch.__file__).resolve().parents[1])
        env["PYTHONPATH"] = repo_pkg + os.pathsep + env.get("PYTHONPATH", "")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "ifcpatch",
                "-i",
                str(source),
                "-o",
                str(cli_output),
                "-r",
                "SplitByBuildingStorey",
                "-l",
                str(output_dir / "ifcpatch.log"),
                "-a",
                str(output_dir),
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 0, completed.stderr
        # -o is the CLI's own output of the patched model, not a storey split.
        _assert_safe_split(tmp_path, output_dir, before, storey_count=1, ignore_outside=(cli_output,))
        assert cli_output.is_file()
        assert sentinel.read_bytes() == _SENTINEL
