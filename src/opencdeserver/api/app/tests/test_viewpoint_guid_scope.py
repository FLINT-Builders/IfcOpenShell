# This file was generated with the assistance of an AI coding tool.
"""Viewpoint creation must not write another project's viewpoint.

POST /bcf/3.0/projects/{project_id}/topics/{topic_id}/viewpoints accepts a
client-chosen guid and creates the viewpoint on the caller's topic. These
tests fail while later queries and the snapshot file still apply that guid
outside the caller's project.
"""

import base64
import os
from pathlib import Path
from uuid import uuid4

from jose import jwt


def bearer(username: str) -> dict:
    secret = Path("/run/secrets/security_secret_key").read_text().rstrip("\n")
    token = jwt.encode(
        {"username": username, "scopes": ["test"]},
        secret,
        algorithm=os.environ["SECURITY_ALGORITHM"],
    )
    return {"Authorization": f"Bearer {token}"}


# Seeded by db_config/init.cypher. kommun can use the victim project only
# among these two; byggherre can use the attacker project and not the victim.
VICTIM_PROJECT = "d1842bfe-a4af-11ed-b9df-0242ac120003"
ATTACKER_PROJECT = "c8e9ccce-a4af-11ed-b9df-0242ac120003"
VICTIM_USER = "kommun"
ATTACKER_USER = "byggherre"

VICTIM_IMAGE = b"victim-snapshot-bytes"
ATTACKER_IMAGE = b"attacker-snapshot-bytes"
VICTIM_COLOR = "111111"
ATTACKER_COLOR = "EEEEEE"
VICTIM_LINE = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
ATTACKER_LINE = (10.0, 20.0, 30.0, 40.0, 50.0, 60.0)
SHARED_COMPONENT = "COMPSHARED"
NEW_COMPONENT = "COMPADDED"


def _topic(api, username, project_id):
    response = api.post(
        f"/bcf/3.0/projects/{project_id}/topics",
        headers=bearer(username),
        json={"title": f"topic-{username}-{uuid4()}", "guid": str(uuid4())},
    )
    assert response.status_code == 201, response.text
    return response.json()["guid"]


def _camera():
    return {
        "camera_view_point": {"x": 0, "y": 0, "z": 0},
        "camera_direction": {"x": 0, "y": 0, "z": -1},
        "camera_up_vector": {"x": 0, "y": 1, "z": 0},
        "field_of_view": 60,
        "aspect_ratio": 1.5,
    }


def _components(ifc_guids, color):
    return {
        "selection": [
            {"ifc_guid": ifc_guid, "originating_system": "scope-test", "authoring_tool_id": color}
            for ifc_guid in ifc_guids
        ],
        "coloring": [{"color": color, "components": [{"ifc_guid": ifc_guid} for ifc_guid in ifc_guids]}],
        "visibility": {
            "default_visibility": True,
            "exceptions": [{"ifc_guid": ifc_guid} for ifc_guid in ifc_guids],
            "view_setup_hints": {
                "spaces_visible": False,
                "space_boundaries_visible": False,
                "openings_visible": False,
            },
        },
    }


def _viewpoint(guid, image, color, ifc_guids, line):
    start = {"x": line[0], "y": line[1], "z": line[2]}
    end = {"x": line[3], "y": line[4], "z": line[5]}
    return {
        "guid": guid,
        "index": 0,
        "perspective_camera": _camera(),
        "lines": [{"start_point": start, "end_point": end}],
        "clipping_planes": [],
        "bitmaps": [],
        "snapshot": {"snapshot_type": "png", "snapshot_data": base64.b64encode(image).decode("ascii")},
        "components": _components(ifc_guids, color),
    }


def _post_viewpoint(api, username, project_id, topic_id, body):
    return api.post(
        f"/bcf/3.0/projects/{project_id}/topics/{topic_id}/viewpoints",
        headers=bearer(username),
        json=body,
    )


def _snapshot(api, username, project_id, topic_id, guid):
    return api.get(
        f"/bcf/3.0/projects/{project_id}/topics/{topic_id}/viewpoints/{guid}/snapshot",
        headers=bearer(username),
    )


def _coloring(api, username, project_id, topic_id, guid):
    return api.get(
        f"/bcf/3.0/projects/{project_id}/topics/{topic_id}/viewpoints/{guid}/coloring",
        headers=bearer(username),
    )


def _selection(api, username, project_id, topic_id, guid):
    return api.get(
        f"/bcf/3.0/projects/{project_id}/topics/{topic_id}/viewpoints/{guid}/selection",
        headers=bearer(username),
    )


def _visibility(api, username, project_id, topic_id, guid):
    return api.get(
        f"/bcf/3.0/projects/{project_id}/topics/{topic_id}/viewpoints/{guid}/visibility",
        headers=bearer(username),
    )


def _seed_ifc_product(graph, ifc_guid):
    # The product query in post_viewpoint matches this shape for every
    # Component with the same ifc guid, in every project.
    graph.execute_query(
        """
        CREATE (prod:IfcProduct {GlobalId: $ifc_guid})
        CREATE (prod)-[:IsDefinedBy]->(:IfcRelationship)-[:RelatingPropertyDefinition]->
               (:IfcPropertySet {Name: 'Reuse'})-[:HasProperties]->(:IfcProperty {Name: 'GTIN'})
               -[:NominalValue]->(:Root {wrappedValue: 'gtin-from-other-graph'})
        """,
        ifc_guid=ifc_guid,
    )


def _victim_markup(graph, project_id, topic_id, guid):
    record = graph.execute_query(
        """
        MATCH (p:Project {project_id: $project_id})-[:HAS]->(t:Topic {guid: $topic_id})
              -[:HAS]->(v:Viewpoint {guid: $guid})-[:HAS]->(l:Line)
        MATCH (v)-[:HAS]->(c:Component {ifc_guid: $ifc_guid})
        OPTIONAL MATCH (c)-[same:SAME_AS]->()
        RETURN l.start_point AS start_point, l.end_point AS end_point,
               c.color AS color, c.GTIN AS gtin, count(same) AS same_as
        """,
        project_id=project_id,
        topic_id=topic_id,
        guid=guid,
        ifc_guid=SHARED_COMPONENT,
        result_transformer_=lambda result: result.single(),
    )
    return record


def test_caller_can_create_a_viewpoint_on_their_own_topic(api):
    topic_id = _topic(api, ATTACKER_USER, ATTACKER_PROJECT)
    guid = str(uuid4())
    created = _post_viewpoint(
        api,
        ATTACKER_USER,
        ATTACKER_PROJECT,
        topic_id,
        _viewpoint(guid, b"own-snapshot", "ABCDEF", ["COMPOWN"], (0.0, 0.0, 0.0, 1.0, 1.0, 1.0)),
    )
    # Lines are stored, but the viewpoint read path currently errors while
    # building line models. A create that did not store a snapshot still fails.
    assert created.status_code in (201, 500)
    snapshot = _snapshot(api, ATTACKER_USER, ATTACKER_PROJECT, topic_id, guid)
    assert snapshot.status_code == 200
    assert snapshot.content == b"own-snapshot"


def test_reused_viewpoint_guid_does_not_change_another_project(api, graph):
    victim_topic = _topic(api, VICTIM_USER, VICTIM_PROJECT)
    attacker_topic = _topic(api, ATTACKER_USER, ATTACKER_PROJECT)
    guid = str(uuid4())

    denied = api.get(
        f"/bcf/3.0/projects/{VICTIM_PROJECT}/topics/{victim_topic}/viewpoints/{guid}",
        headers=bearer(ATTACKER_USER),
    )
    assert denied.status_code == 404

    victim_create = _post_viewpoint(
        api,
        VICTIM_USER,
        VICTIM_PROJECT,
        victim_topic,
        _viewpoint(guid, VICTIM_IMAGE, VICTIM_COLOR, [SHARED_COMPONENT], VICTIM_LINE),
    )
    assert victim_create.status_code in (201, 500)
    baseline = _snapshot(api, VICTIM_USER, VICTIM_PROJECT, victim_topic, guid)
    assert baseline.status_code == 200
    assert baseline.content == VICTIM_IMAGE
    baseline_color = _coloring(api, VICTIM_USER, VICTIM_PROJECT, victim_topic, guid)
    assert baseline_color.status_code == 200
    assert baseline_color.json()["coloring"][0]["color"] == VICTIM_COLOR

    _seed_ifc_product(graph, SHARED_COMPONENT)

    attack = _post_viewpoint(
        api,
        ATTACKER_USER,
        ATTACKER_PROJECT,
        attacker_topic,
        _viewpoint(guid, ATTACKER_IMAGE, ATTACKER_COLOR, [SHARED_COMPONENT, NEW_COMPONENT], ATTACKER_LINE),
    )
    # The response may be an error. A refusal that already replaced the
    # victim snapshot, markup, or component links is still a failure.
    assert attack.status_code in (201, 400, 404, 409, 422, 500)

    snapshot = _snapshot(api, VICTIM_USER, VICTIM_PROJECT, victim_topic, guid)
    assert snapshot.status_code == 200
    assert snapshot.content == VICTIM_IMAGE
    snapshot_path = f"data/snapshots/snapshot_{guid}.png"
    with open(snapshot_path, "rb") as snapshot_file:
        assert snapshot_file.read() == VICTIM_IMAGE

    coloring = _coloring(api, VICTIM_USER, VICTIM_PROJECT, victim_topic, guid)
    assert coloring.status_code == 200
    colors = coloring.json()["coloring"]
    assert [entry["color"] for entry in colors] == [VICTIM_COLOR]
    colored_ids = [component["ifc_guid"] for entry in colors for component in entry["components"]]
    assert colored_ids == [SHARED_COMPONENT]

    selection = _selection(api, VICTIM_USER, VICTIM_PROJECT, victim_topic, guid)
    assert selection.status_code == 200
    selected = selection.json()["selection"]
    assert [component["ifc_guid"] for component in selected] == [SHARED_COMPONENT]
    assert selected[0]["authoring_tool_id"] == VICTIM_COLOR

    visibility = _visibility(api, VICTIM_USER, VICTIM_PROJECT, victim_topic, guid)
    assert visibility.status_code == 200
    exceptions = visibility.json()["visibility"]["exceptions"]
    assert [component["ifc_guid"] for component in exceptions] == [SHARED_COMPONENT]
    assert exceptions[0]["authoring_tool_id"] == VICTIM_COLOR

    stored = _victim_markup(graph, VICTIM_PROJECT, victim_topic, guid)
    assert stored is not None
    assert (stored["start_point"].x, stored["start_point"].y, stored["start_point"].z) == VICTIM_LINE[:3]
    assert (stored["end_point"].x, stored["end_point"].y, stored["end_point"].z) == VICTIM_LINE[3:]
    assert stored["color"] == VICTIM_COLOR
    assert stored["gtin"] is None
    assert stored["same_as"] == 0
