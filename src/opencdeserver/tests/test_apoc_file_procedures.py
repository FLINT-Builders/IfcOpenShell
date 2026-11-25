# This file was generated with the assistance of an AI coding tool.
"""Database logins must not read or write files through the OpenCDE Neo4j server.

The OpenCDE Compose file starts Neo4j 5.7.0 with the repository's APOC config and
plugin jars. These tests boot that same server the way
``neo4j/docker-neo4j-publish`` ``5.7.0/community/local-package/docker-entrypoint.sh``
(git commit 6182834d87cadbe06c1a8a54f5b033bcb3ff82dd) applies the Compose mounts and
``NEO4J_*`` settings, then log in over Bolt.

They fail while a login can read the import mount, write the import mount, or read
the log mount. They pass once those calls are rejected and do not create files or
graph nodes. Java 17 is required because that is the runtime in the Neo4j 5.7.0
image named by ``docker-compose.yml``.

Run:

    python3 -m pytest src/opencdeserver/tests/test_apoc_file_procedures.py

Left untested, because they are not a local file read or write on this classpath:

- ``apoc.export.json.data``, ``apoc.export.json.graph``
- ``apoc.export.csv.data``, ``apoc.export.csv.graph``
- ``apoc.export.cypher.data``, ``apoc.export.cypher.graph``, ``apoc.export.cypher.schema``
- ``apoc.export.graphml.data``, ``apoc.export.graphml.graph``
- ``apoc.export.arrow.*`` (the shipped jars have no Arrow buffer allocator, so the
  call fails before it opens a file)
- ``apoc.load.arrow``, ``apoc.load.arrow.stream``, ``apoc.load.csvParams``
- ``apoc.load.jdbc``, ``apoc.load.jdbcUpdate``, ``apoc.load.ldap``, ``apoc.load.driver``
- ``apoc.load.directory.async.*``
- ``apoc.metrics.get``, ``apoc.metrics.list``, ``apoc.metrics.storage``
- ``apoc.config.list``
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import textwrap
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pytest

OPENCDE = Path(__file__).resolve().parents[1]
COMPOSE_FILE = OPENCDE / "docker-compose.yml"
CONF_MOUNT = OPENCDE / "neo4j" / "conf"
PLUGIN_DIR = OPENCDE / "neo4j" / "plugins"

# Image library/neo4j:5.7.0-community, Dockerfile NEO4J_SHA256 at the commit above.
NEO4J_TARBALL_URL = "https://dist.neo4j.org/neo4j-community-5.7.0-unix.tar.gz"
NEO4J_TARBALL_SHA256 = "e13e94d8c8730f9525f30f98821ade79b349af1697d7ac94a8c3cc8b0273b734"

# Operator .env values are not in the repository. The Docker entrypoint rejects
# any other initial username and refuses a password equal to the default.
PLACEHOLDER_USER = "neo4j"
PLACEHOLDER_PASSWORD = "placeholder-password"

NOT_CONFIGS = {
    "NEO4J_ACCEPT_LICENSE_AGREEMENT",
    "NEO4J_AUTH",
    "NEO4J_DEBUG",
    "NEO4J_EDITION",
    "NEO4J_HOME",
    "NEO4J_PLUGINS",
    "NEO4J_SHA256",
    "NEO4J_TARBALL",
}

READ_CALLS = [
    ("apoc.load.json", "CALL apoc.load.json('canary.json') YIELD value RETURN value.marker", "import-canary"),
    (
        "apoc.load.jsonArray",
        "CALL apoc.load.jsonArray('array.json') YIELD value RETURN value.marker",
        "array-canary",
    ),
    (
        "apoc.load.jsonParams",
        "CALL apoc.load.jsonParams('canary.json', {}, '$.marker') YIELD value RETURN value.marker",
        "import-canary",
    ),
    ("apoc.load.csv", "CALL apoc.load.csv('canary.csv') YIELD map RETURN map.marker", "csv-canary"),
    ("apoc.load.xml", "CALL apoc.load.xml('canary.xml') YIELD value RETURN value", "xml-canary"),
    (
        "apoc.load.html",
        "CALL apoc.load.html('canary.html', {node: 'body'}) YIELD value RETURN value",
        "html-canary",
    ),
    (
        "apoc.load.htmlPlainText",
        "CALL apoc.load.htmlPlainText('canary.html') YIELD value RETURN value",
        None,
    ),
    ("LOAD CSV", "LOAD CSV WITH HEADERS FROM 'file:///canary.csv' AS row RETURN row.marker", "csv-canary"),
]

WRITE_CALLS = [
    (
        "apoc.export.json.query",
        "CALL apoc.export.json.query('RETURN 1 AS n', 'planted-json-query.json', {}) YIELD file RETURN file",
        "planted-json-query.json",
    ),
    (
        "apoc.export.json.all",
        "CALL apoc.export.json.all('planted-json-all.json', {}) YIELD file RETURN file",
        "planted-json-all.json",
    ),
    (
        "apoc.export.csv.query",
        "CALL apoc.export.csv.query('RETURN 1 AS n', 'planted-csv-query.csv', {}) YIELD file RETURN file",
        "planted-csv-query.csv",
    ),
    (
        "apoc.export.csv.all",
        "CALL apoc.export.csv.all('planted-csv-all.csv', {}) YIELD file RETURN file",
        "planted-csv-all.csv",
    ),
    (
        "apoc.export.cypher.query",
        "CALL apoc.export.cypher.query('RETURN 1 AS n', 'planted-cypher-query.cypher', {}) YIELD file RETURN file",
        "planted-cypher-query.cypher",
    ),
    (
        "apoc.export.cypher.all",
        "CALL apoc.export.cypher.all('planted-cypher-all.cypher', {}) YIELD file RETURN file",
        "planted-cypher-all.cypher",
    ),
    (
        "apoc.export.graphml.query",
        "CALL apoc.export.graphml.query('RETURN 1 AS n', 'planted-graphml-query.graphml', {}) YIELD file RETURN file",
        "planted-graphml-query.graphml",
    ),
    (
        "apoc.export.graphml.all",
        "CALL apoc.export.graphml.all('planted-graphml-all.graphml', {}) YIELD file RETURN file",
        "planted-graphml-all.graphml",
    ),
]


@dataclass
class Neo4jServer:
    home: Path
    import_dir: Path
    logs_dir: Path
    data_dir: Path
    bolt: str
    env: dict[str, str]

    def cypher(
        self,
        statement: str,
        user: str = PLACEHOLDER_USER,
        password: str = PLACEHOLDER_PASSWORD,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                str(self.home / "bin" / "cypher-shell"),
                "-a",
                self.bolt,
                "-u",
                user,
                "-p",
                password,
                "--format",
                "plain",
                statement,
            ],
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )


def _java_home() -> Path:
    candidates = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]))
    candidates.append(Path("/usr/lib/jvm/java-17-openjdk-amd64"))
    for home in candidates:
        java = home / "bin" / "java"
        if not java.is_file():
            continue
        completed = subprocess.run([str(java), "-version"], text=True, capture_output=True, check=False)
        version_text = completed.stdout + completed.stderr
        if 'version "17' in version_text:
            return home
    raise RuntimeError("Java 17 is required to run the Neo4j 5.7.0 server used by OpenCDE")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _neo4j_distribution() -> Path:
    cache = Path(tempfile.gettempdir()) / "ifcopenshell-neo4j-5.7.0"
    tarball = cache / "neo4j-community-5.7.0-unix.tar.gz"
    extracted = cache / "neo4j-community-5.7.0"
    cache.mkdir(parents=True, exist_ok=True)
    if not tarball.is_file() or _sha256(tarball) != NEO4J_TARBALL_SHA256:
        urllib.request.urlretrieve(NEO4J_TARBALL_URL, tarball)
    if _sha256(tarball) != NEO4J_TARBALL_SHA256:
        raise RuntimeError("Neo4j 5.7.0 tarball checksum does not match the 5.7.0 community image")
    if not (extracted / "bin" / "neo4j").is_file():
        with tarfile.open(tarball) as archive:
            archive.extractall(cache, filter="data")
    return extracted


def _compose_neo4j_environment(compose_text: str) -> list[str]:
    in_service = False
    in_environment = False
    entries: list[str] = []
    for line in compose_text.splitlines():
        if line.startswith("  neo4j:"):
            in_service = True
            continue
        if in_service and line.startswith("  ") and not line.startswith("    ") and line.strip():
            break
        if in_service and line.startswith("    environment:"):
            in_environment = True
            continue
        if not in_environment:
            continue
        if line.startswith("    ") and not line.startswith("      "):
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            entries.append(stripped[2:].strip())
    if not entries:
        raise RuntimeError(f"no neo4j environment entries in {COMPOSE_FILE}")
    return entries


def _expand_compose(value: str, env: dict[str, str]) -> str:
    expanded = value
    for name, replacement in env.items():
        expanded = expanded.replace("${" + name + "}", replacement)
    return expanded


def _setting_name(env_name: str) -> str:
    without_prefix = env_name[len("NEO4J_") :]
    return without_prefix.replace("_", ".").replace("..", "_")


def _upsert(conf_file: Path, setting: str, value: str) -> None:
    lines = conf_file.read_text().splitlines() if conf_file.exists() else []
    kept = [line for line in lines if not line.startswith(setting + "=")]
    kept.append(f"{setting}={value}")
    conf_file.write_text("\n".join(kept) + "\n")


def _write_product_config(home: Path, import_dir: Path, logs_dir: Path, plugins_dir: Path, env: dict[str, str]) -> None:
    conf_dir = home / "conf"
    shutil.rmtree(conf_dir)
    conf_dir.mkdir()
    for source in CONF_MOUNT.iterdir():
        if source.is_file():
            shutil.copy(source, conf_dir / source.name)
    neo4j_conf = conf_dir / "neo4j.conf"
    neo4j_conf.touch()

    # docker-entrypoint.sh sets these when the matching mount exists and Compose
    # did not set them. OpenCDE mounts /import, /logs, and /plugins.
    mount_defaults = {
        "NEO4J_server_directories_import": str(import_dir),
        "NEO4J_server_directories_logs": str(logs_dir),
        "NEO4J_server_directories_plugins": str(plugins_dir),
    }
    applied: dict[str, str] = {}
    for entry in _compose_neo4j_environment(COMPOSE_FILE.read_text()):
        if "=" in entry:
            name, value = entry.split("=", 1)
        else:
            name, value = entry, ""
        applied[name] = _expand_compose(value, env)
    for name, value in mount_defaults.items():
        applied.setdefault(name, value)

    # Docker-specific defaults from docker-entrypoint.sh. They do not override a
    # setting already written by the operator.
    for setting, value in (
        ("db.tx_log.rotation.retention_policy", "100M size"),
        ("server.memory.pagecache.size", "512M"),
        ("server.default_listen_address", "0.0.0.0"),
    ):
        if not any(line.startswith(setting + "=") for line in neo4j_conf.read_text().splitlines()):
            _upsert(neo4j_conf, setting, value)

    for name, value in applied.items():
        if name in NOT_CONFIGS or name == "NEO4J_AUTH" or not value:
            continue
        setting = _setting_name(name)
        target = conf_dir / "apoc.conf" if setting.startswith("apoc.") else neo4j_conf
        _upsert(target, setting, value)

    # Loopback ports and a small heap keep this harness local. They are applied
    # after the product settings and do not change the APOC file configuration.
    for setting, value in (
        ("server.default_listen_address", "127.0.0.1"),
        ("server.bolt.listen_address", "127.0.0.1:17687"),
        ("server.http.listen_address", "127.0.0.1:17474"),
        ("server.https.listen_address", "127.0.0.1:17473"),
        ("server.memory.heap.initial_size", "256m"),
        ("server.memory.heap.max_size", "512m"),
        ("server.memory.pagecache.size", "64m"),
    ):
        _upsert(neo4j_conf, setting, value)


def _seed_files(import_dir: Path, logs_dir: Path, data_dir: Path) -> None:
    (import_dir / "canary.json").write_text('{"marker":"import-canary"}\n')
    (import_dir / "array.json").write_text('[{"marker":"array-canary"}]\n')
    (import_dir / "canary.csv").write_text("marker\ncsv-canary\n")
    (import_dir / "canary.xml").write_text("<root><item>xml-canary</item></root>\n")
    (import_dir / "canary.html").write_text("<html><body>html-canary</body></html>\n")
    (import_dir / "nodes.json").write_text(
        '{"type":"node","id":"1","labels":["Canary"],"properties":{"marker":"imported-node"}}\n'
    )
    (import_dir / "nodes.csv").write_text("name\ncsv-imported\n")
    (import_dir / "canary.graphml").write_text(
        textwrap.dedent(
            """\
            <?xml version="1.0" encoding="UTF-8"?>
            <graphml xmlns="http://graphml.graphdrawing.org/xmlns">
              <graph id="G" edgedefault="directed"><node id="n0"/></graph>
            </graphml>
            """
        )
    )
    (logs_dir / "canary.log").write_text("log-canary\n")
    (data_dir / "canary.txt").write_text("data-canary\n")


def _assert_rejected(result: subprocess.CompletedProcess[str], planted: Path | None = None) -> None:
    if planted is not None:
        assert not planted.exists(), f"{planted.name} was created"
    assert result.returncode != 0, result.stdout + result.stderr


@pytest.fixture(scope="module")
def server() -> Neo4jServer:
    java_home = _java_home()
    distribution = _neo4j_distribution()
    work = Path(tempfile.mkdtemp(prefix="opencde-apoc-"))
    home = work / "home"
    import_dir = work / "import"
    logs_dir = work / "logs"
    data_dir = work / "data"
    plugins_dir = work / "plugins"
    for path in (import_dir, logs_dir, data_dir, plugins_dir):
        path.mkdir()
    shutil.copytree(distribution, home)
    shutil.rmtree(home / "data")
    shutil.rmtree(home / "logs")
    (home / "data").symlink_to(data_dir)
    (home / "logs").symlink_to(logs_dir)
    for jar in PLUGIN_DIR.glob("apoc-*.jar"):
        shutil.copy(jar, plugins_dir / jar.name)
    env = os.environ.copy()
    env["JAVA_HOME"] = str(java_home)
    env["NEO4J_HOME"] = str(home)
    env["NEO4J_USER"] = PLACEHOLDER_USER
    env["NEO4J_INITIAL_PASSWORD"] = PLACEHOLDER_PASSWORD
    _write_product_config(home, import_dir, logs_dir, plugins_dir, env)
    _seed_files(import_dir, logs_dir, data_dir)
    admin = subprocess.run(
        [str(home / "bin" / "neo4j-admin"), "dbms", "set-initial-password", PLACEHOLDER_PASSWORD],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if admin.returncode != 0:
        raise RuntimeError(admin.stdout + admin.stderr)
    started = subprocess.run(
        [str(home / "bin" / "neo4j"), "start"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    bolt = "bolt://127.0.0.1:17687"
    ready = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=started.stderr)
    for _ in range(60):
        ready = subprocess.run(
            [
                str(home / "bin" / "cypher-shell"),
                "-a",
                bolt,
                "-u",
                PLACEHOLDER_USER,
                "-p",
                PLACEHOLDER_PASSWORD,
                "RETURN 1",
            ],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if ready.returncode == 0:
            break
        subprocess.run(["sleep", "1"], check=False)
    running = Neo4jServer(home, import_dir, logs_dir, data_dir, bolt, env)
    try:
        if ready.returncode != 0:
            log_path = logs_dir / "neo4j.log"
            log_text = log_path.read_text() if log_path.exists() else ""
            raise RuntimeError(started.stdout + started.stderr + ready.stdout + ready.stderr + log_text)
        created = running.cypher(
            "CREATE USER reader IF NOT EXISTS SET PASSWORD '" + PLACEHOLDER_PASSWORD + "' CHANGE NOT REQUIRED"
        )
        if created.returncode != 0:
            created = running.cypher(
                "CREATE USER reader SET PASSWORD '" + PLACEHOLDER_PASSWORD + "' CHANGE NOT REQUIRED"
            )
        if created.returncode != 0:
            raise RuntimeError(created.stdout + created.stderr)
        yield running
    finally:
        subprocess.run([str(home / "bin" / "neo4j"), "stop"], env=env, text=True, capture_output=True, check=False)
        shutil.rmtree(work, ignore_errors=True)


def test_ordinary_cypher_still_works(server: Neo4jServer) -> None:
    result = server.cypher("RETURN 1 AS ok")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1" in result.stdout


def test_unauthenticated_bolt_is_rejected(server: Neo4jServer) -> None:
    result = subprocess.run(
        [str(server.home / "bin" / "cypher-shell"), "-a", server.bolt, "RETURN 1"],
        env=server.env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0


def test_ttl_helper_the_application_calls_remains_available(server: Neo4jServer) -> None:
    result = server.cypher(
        "CREATE (n:TtlProbe {marker: 'ttl'}) WITH n CALL apoc.ttl.expireIn(n, 3600, 's') RETURN n.marker"
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(("procedure", "statement", "marker"), READ_CALLS, ids=[item[0] for item in READ_CALLS])
def test_database_login_cannot_read_import_files(
    server: Neo4jServer, procedure: str, statement: str, marker: str | None
) -> None:
    del procedure
    result = server.cypher(statement)
    _assert_rejected(result)
    if marker is not None:
        assert marker not in result.stdout


def test_database_login_cannot_list_import_directory(server: Neo4jServer) -> None:
    statement = "CALL apoc.load.directory('canary.json', $url) YIELD value RETURN value".replace(
        "$url", "'" + server.import_dir.as_uri() + "'"
    )
    result = server.cypher(statement)
    _assert_rejected(result)
    assert "canary.json" not in result.stdout


@pytest.mark.parametrize(("procedure", "statement", "filename"), WRITE_CALLS, ids=[item[0] for item in WRITE_CALLS])
def test_database_login_cannot_write_import_files(
    server: Neo4jServer, procedure: str, statement: str, filename: str
) -> None:
    del procedure
    planted = server.import_dir / filename
    if planted.exists():
        planted.unlink()
    result = server.cypher(statement)
    _assert_rejected(result, planted)


def test_import_procedures_do_not_load_files_into_the_graph(server: Neo4jServer) -> None:
    constraint = server.cypher(
        "CREATE CONSTRAINT canary_import IF NOT EXISTS FOR (n:Canary) REQUIRE n.neo4jImportId IS UNIQUE"
    )
    if constraint.returncode != 0:
        constraint = server.cypher("CREATE CONSTRAINT FOR (n:Canary) REQUIRE n.neo4jImportId IS UNIQUE")
    assert constraint.returncode == 0, constraint.stdout + constraint.stderr

    calls = [
        ("CALL apoc.import.json('nodes.json') YIELD nodes RETURN nodes", "MATCH (n:Canary) RETURN count(n) AS c"),
        (
            "CALL apoc.import.csv([{fileName: 'nodes.csv', labels: ['CsvCanary']}], [], {}) YIELD nodes RETURN nodes",
            "MATCH (n:CsvCanary) RETURN count(n) AS c",
        ),
        ("CALL apoc.import.xml('canary.xml') YIELD node RETURN node", "MATCH (n:XmlDocument) RETURN count(n) AS c"),
        (
            "CALL apoc.import.graphml('canary.graphml', {}) YIELD nodes RETURN nodes",
            "MATCH (n) WHERE n.graphml_id = 'n0' OR n.id = 'n0' RETURN count(n) AS c",
        ),
    ]
    for call, count_query in calls:
        result = server.cypher(call)
        counted = server.cypher(count_query)
        assert counted.returncode == 0, counted.stdout + counted.stderr
        last = counted.stdout.strip().splitlines()[-1]
        assert last == "0", counted.stdout
        _assert_rejected(result)


def test_database_login_cannot_read_log_mount(server: Neo4jServer) -> None:
    result = server.cypher("CALL apoc.log.stream('canary.log', {last: 5}) YIELD line RETURN line")
    _assert_rejected(result)
    assert "log-canary" not in result.stdout


def test_database_login_cannot_read_data_mount_or_escape_import(server: Neo4jServer) -> None:
    data_uri = server.data_dir.as_uri() + "/canary.txt"
    logs_uri = server.logs_dir.as_uri() + "/canary.log"
    reads = [
        f"CALL apoc.load.json('{data_uri}') YIELD value RETURN value",
        f"CALL apoc.load.json('{logs_uri}') YIELD value RETURN value",
        "CALL apoc.log.stream('../data/canary.txt', {last: 5}) YIELD line RETURN line",
        f"CALL apoc.log.stream('{server.data_dir / 'canary.txt'}', {{last: 5}}) YIELD line RETURN line",
        "LOAD CSV FROM 'file:///../logs/canary.log' AS row RETURN row",
    ]
    for statement in reads:
        result = server.cypher(statement)
        _assert_rejected(result)
        assert "data-canary" not in result.stdout
        assert "log-canary" not in result.stdout
    outside = server.logs_dir / "planted-outside.json"
    result = server.cypher(
        "CALL apoc.export.json.query('RETURN 1 AS n', '" + str(outside) + "', {}) YIELD file RETURN file"
    )
    _assert_rejected(result, outside)


def test_second_database_user_cannot_read_or_write_files(server: Neo4jServer) -> None:
    read = server.cypher("CALL apoc.load.json('canary.json') YIELD value RETURN value.marker", user="reader")
    _assert_rejected(read)
    assert "import-canary" not in read.stdout
    logs = server.cypher("CALL apoc.log.stream('canary.log', {last: 5}) YIELD line RETURN line", user="reader")
    _assert_rejected(logs)
    assert "log-canary" not in logs.stdout
    planted = server.import_dir / "reader-planted.json"
    if planted.exists():
        planted.unlink()
    write = server.cypher(
        "CALL apoc.export.json.query('RETURN 1 AS n', 'reader-planted.json', {}) YIELD file RETURN file",
        user="reader",
    )
    _assert_rejected(write, planted)
