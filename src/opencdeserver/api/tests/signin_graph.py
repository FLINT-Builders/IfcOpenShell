# This file was generated with the assistance of an AI coding tool.
"""In-memory stand-in for the Neo4j driver calls the OpenCDE sign-in path makes.

The product opens a session and runs a unit of work with ``execute_read`` /
``execute_write`` (neo4j 5.9.0 ``Session._run_transaction`` calls the unit of
work once as ``transaction_function(tx, *args, **kwargs)`` and returns its
result). ``Transaction.run`` forwards the Cypher text and parameters and
returns a result that supports iteration, ``single()``, and ``consume()``.

This stand-in performs those same steps for the statements this path runs:
the startup script, user lookup, authorization-code creation, code exchange,
and project listing. It does not open a network connection.
"""

from __future__ import annotations


class GraphNode:
    def __init__(self, labels, props):
        self.labels = set(labels)
        self.props = dict(props)

    def items(self):
        return self.props.items()


class GraphRecord:
    def __init__(self, values):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


class SummaryCounters:
    def __init__(self, nodes_created=0, nodes_deleted=0):
        self.nodes_created = nodes_created
        self.nodes_deleted = nodes_deleted


class ResultSummary:
    def __init__(self, nodes_created=0, nodes_deleted=0):
        self.counters = SummaryCounters(nodes_created, nodes_deleted)


class GraphResult:
    def __init__(self, records, nodes_created=0, nodes_deleted=0):
        self._records = list(records)
        self._summary = ResultSummary(nodes_created, nodes_deleted)

    def __iter__(self):
        yield from self._records

    def single(self, strict=False):
        if not self._records:
            return None
        return self._records[0]

    def consume(self):
        return self._summary


class GraphRelationship:
    def __init__(self, source, rel_type, props, target):
        self.source = source
        self.rel_type = rel_type
        self.props = dict(props)
        self.target = target


class SigninGraph:
    def __init__(self):
        self.nodes = []
        self.rels = []

    def user(self, username):
        for node in self.nodes:
            if "User" in node.labels and node.props.get("username") == username:
                return node
        return None

    def execute(self, query, params):
        collapsed = " ".join(query.split())
        if collapsed.startswith("MATCH (n) DETACH DELETE"):
            deleted = len(self.nodes)
            self.nodes.clear()
            self.rels.clear()
            return GraphResult([], nodes_deleted=deleted)
        if collapsed.startswith("CREATE"):
            before = len(self.nodes)
            CreateParser(collapsed, self).parse()
            return GraphResult([], nodes_created=len(self.nodes) - before)
        if "RETURN u AS user" in collapsed and "LIMIT 1" in collapsed:
            return self._get_user(params)
        if "ac:AuthorizationCode" in collapsed and "apoc.ttl.expireIn" in collapsed:
            return self._create_authorization_code(params)
        if "ac.code = $authorization_code" in collapsed and "RETURN username, scope" in collapsed:
            return self._read_authorization_code(params)
        if "Token:AccessToken" in collapsed and "ac1.code = $authorization_code" in collapsed:
            return self._exchange_authorization_code(params)
        if "RETURN p AS project" in collapsed and "HAS_ACTIONS_ON" in collapsed and "$project_id" not in collapsed:
            return self._get_projects(params)
        raise AssertionError("sign-in stand-in has no result for this statement: " + collapsed[:180])

    def _get_user(self, params):
        node = self.user(params["username"])
        if node is None:
            return GraphResult([])
        return GraphResult([GraphRecord({"user": node})])

    def _auth_code_node(self, user):
        for rel in self.rels:
            if rel.source is user and rel.rel_type == "CAN_USE" and "AuthorizationCode" in rel.target.labels:
                return rel.target
        return None

    def _create_authorization_code(self, params):
        user = self.user(params["username"])
        if user is None:
            return GraphResult([], nodes_created=0)
        self.rels = [
            rel
            for rel in self.rels
            if not (rel.source is user and rel.rel_type == "CAN_USE" and "Token" in rel.target.labels)
        ]
        created = 0
        node = self._auth_code_node(user)
        if node is None:
            node = GraphNode(["AuthorizationCode"], {})
            self.nodes.append(node)
            self.rels.append(GraphRelationship(user, "CAN_USE", {}, node))
            created = 1
        node.props["code"] = params["authorization_code"]
        node.props["scope"] = params["scope"]
        node.props["ttl_seconds"] = params["time_delta"]
        return GraphResult([GraphRecord({"authorization_code": node})], nodes_created=created)

    def _code_owner(self, code):
        for rel in self.rels:
            if (
                rel.rel_type == "CAN_USE"
                and "AuthorizationCode" in rel.target.labels
                and rel.target.props.get("code") == code
            ):
                return rel.source, rel.target
        return None, None

    def _read_authorization_code(self, params):
        user, node = self._code_owner(params["authorization_code"])
        if node is None:
            return GraphResult([])
        return GraphResult([GraphRecord({"username": user.props["username"], "scope": node.props.get("scope")})])

    def _exchange_authorization_code(self, params):
        user, node = self._code_owner(params["authorization_code"])
        if node is None or user is None or user.props.get("username") != params["username"]:
            return GraphResult([], nodes_created=0, nodes_deleted=0)
        self.nodes.remove(node)
        self.rels = [rel for rel in self.rels if rel.target is not node and rel.source is not node]
        access = GraphNode(
            ["Token", "AccessToken"], {"value": params["access_token"], "hash": params["access_token_hash"]}
        )
        refresh = GraphNode(
            ["Token", "RefreshToken"], {"value": params["refresh_token"], "hash": params["refresh_token_hash"]}
        )
        self.nodes.extend([access, refresh])
        self.rels.append(GraphRelationship(user, "CAN_USE", {}, access))
        self.rels.append(GraphRelationship(user, "CAN_USE", {}, refresh))
        return GraphResult([], nodes_created=2, nodes_deleted=1)

    def _get_projects(self, params):
        records = []
        for rel in self.rels:
            if rel.rel_type != "HAS_ACTIONS_ON" or rel.props.get("read") is not True:
                continue
            if "User" not in rel.source.labels or rel.source.props.get("username") != params["username"]:
                continue
            if "Project" not in rel.target.labels:
                continue
            records.append(GraphRecord({"project": rel.target}))
        return GraphResult(records)


class CreateParser:
    def __init__(self, text, graph):
        self.text = text
        self.n = len(text)
        self.i = 0
        self.graph = graph
        self.variables = {}

    def parse(self):
        self.skip_ws()
        if self.text[self.i : self.i + 6].upper() != "CREATE":
            raise AssertionError("expected CREATE")
        self.i += 6
        while True:
            self.skip_ws()
            if self.i >= self.n:
                return
            if self.peek() == ",":
                self.i += 1
                continue
            if self.peek() != "(":
                return
            source = self.parse_node()
            self.skip_ws()
            if self.text.startswith("-[", self.i):
                rel_type, props = self.parse_relationship()
                target = self.parse_node()
                self.graph.rels.append(GraphRelationship(source, rel_type, props, target))

    def parse_node(self):
        if self.peek() != "(":
            raise AssertionError("expected node at %s" % self.i)
        self.i += 1
        name = self.parse_ident()
        labels = []
        while self.peek() == ":":
            self.i += 1
            labels.append(self.parse_ident())
        self.skip_ws()
        props = {}
        if self.peek() == "{":
            props = self.parse_map()
        self.skip_ws()
        if self.peek() != ")":
            raise AssertionError("expected ) at %s" % self.i)
        self.i += 1
        if not labels and not props and name in self.variables:
            return self.variables[name]
        node = GraphNode(labels, props)
        self.variables[name] = node
        self.graph.nodes.append(node)
        return node

    def parse_relationship(self):
        if not self.text.startswith("-[", self.i):
            raise AssertionError("expected relationship at %s" % self.i)
        self.i += 2
        self.parse_ident()
        if self.peek() != ":":
            raise AssertionError("expected relationship type")
        self.i += 1
        rel_type = self.parse_ident()
        while self.peek() == ":":
            self.i += 1
            rel_type = self.parse_ident()
        self.skip_ws()
        props = {}
        if self.peek() == "{":
            props = self.parse_map()
        self.skip_ws()
        if self.peek() != "]":
            raise AssertionError("expected ] at %s" % self.i)
        self.i += 1
        if not self.text.startswith("->", self.i):
            raise AssertionError("expected -> at %s" % self.i)
        self.i += 2
        return rel_type, props

    def parse_map(self):
        if self.peek() != "{":
            raise AssertionError("expected {")
        self.i += 1
        props = {}
        while True:
            self.skip_ws()
            if self.peek() == "}":
                self.i += 1
                return props
            key = self.parse_ident()
            self.skip_ws()
            if self.peek() != ":":
                raise AssertionError("expected : at %s" % self.i)
            self.i += 1
            props[key] = self.parse_value()
            self.skip_ws()
            if self.peek() == ",":
                self.i += 1

    def parse_list(self):
        if self.peek() != "[":
            raise AssertionError("expected [")
        self.i += 1
        values = []
        while True:
            self.skip_ws()
            if self.peek() == "]":
                self.i += 1
                return values
            values.append(self.parse_value())
            self.skip_ws()
            if self.peek() == ",":
                self.i += 1

    def parse_value(self):
        self.skip_ws()
        char = self.peek()
        if char in ("'", '"'):
            return self.parse_string()
        if char == "[":
            return self.parse_list()
        if char == "{":
            return self.parse_map()
        if char.isdigit() or char == "-":
            return self.parse_number()
        word = self.parse_ident()
        lowered = word.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered == "null":
            return None
        raise AssertionError("unsupported value %s" % word)

    def parse_string(self):
        quote = self.peek()
        if quote not in ("'", '"'):
            raise AssertionError("expected string")
        self.i += 1
        start = self.i
        while self.i < self.n and self.text[self.i] != quote:
            self.i += 1
        value = self.text[start : self.i]
        self.i += 1
        return value

    def parse_number(self):
        start = self.i
        if self.peek() == "-":
            self.i += 1
        while self.i < self.n and (self.text[self.i].isdigit() or self.text[self.i] == "."):
            self.i += 1
        token = self.text[start : self.i]
        if "." in token:
            return float(token)
        return int(token)

    def parse_ident(self):
        self.skip_ws()
        start = self.i
        while self.i < self.n and (self.text[self.i].isalnum() or self.text[self.i] == "_"):
            self.i += 1
        if start == self.i:
            raise AssertionError("expected identifier at %s" % self.i)
        return self.text[start : self.i]

    def skip_ws(self):
        while self.i < self.n and self.text[self.i].isspace():
            self.i += 1

    def peek(self):
        if self.i >= self.n:
            return ""
        return self.text[self.i]


class SigninSession:
    def __init__(self, graph):
        self.graph = graph

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute_read(self, transaction_function, *args, **kwargs):
        return transaction_function(SigninTransaction(self.graph), *args, **kwargs)

    def execute_write(self, transaction_function, *args, **kwargs):
        return transaction_function(SigninTransaction(self.graph), *args, **kwargs)


class SigninTransaction:
    def __init__(self, graph):
        self.graph = graph

    def run(self, query, parameters=None, **kwparameters):
        params = dict(parameters or {})
        params.update(kwparameters)
        return self.graph.execute(query, params)


class SigninDriver:
    def __init__(self, graph):
        self.graph = graph

    def verify_connectivity(self, **config):
        return None

    def session(self, **config):
        return SigninSession(self.graph)


GRAPH = SigninGraph()
DRIVER = SigninDriver(GRAPH)
