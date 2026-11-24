# This file was generated with the assistance of an AI coding tool.
"""Open IDS XML the way the IfcTester web worker does.

The worker calls ``api.ids_from_xml_string`` and then ``Ids.asdict``.
"""

import json
import sys

from api import ids_from_xml_string


def main() -> None:
    xml = sys.stdin.read()
    document = ids_from_xml_string(xml, False)
    json.dump(document.asdict(), sys.stdout)


if __name__ == "__main__":
    main()
