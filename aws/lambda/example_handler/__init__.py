import os
import tempfile

import boto3
import ifcopenshell
import ifcopenshell.util.element

s3 = boto3.client("s3")

# Created with mode 0700 once per execution environment, so its entries are only ever made by this handler.
DOWNLOAD_DIR = os.path.realpath(tempfile.mkdtemp(prefix="ifc_downloads_", dir="/tmp"))


def get_download_path(filename):
    if not isinstance(filename, str) or filename in ("", ".", "..") or any(c in filename for c in "/\\\0"):
        return None
    path = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.dirname(os.path.realpath(path)) != DOWNLOAD_DIR:
        return None
    return path


def extract_wall_psets_handler(event, context):
    print("Hello from lambda")
    print("Event: {}".format(event))
    print("Context: {}".format(context))

    filename = event["body"]["filename"]
    path = get_download_path(filename)
    if path is None:
        return {"statusCode": 400, "body": "Invalid filename"}

    s3.download_file("my_ifc_files_bucket", filename, path)
    ifc_file = ifcopenshell.open(path)
    walls = ifc_file.by_type("IfcWall")

    psets = []
    for wall in walls:
        wall_data = ifcopenshell.util.element.get_psets(wall)
        wall_data["id"] = wall.GlobalId
        psets.append(wall_data)

    return {"statusCode": 200, "body": psets}
