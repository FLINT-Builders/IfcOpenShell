# This file was generated with the assistance of an AI coding tool.
"""Save Drawing.open_with_user_command before other tool tests replace it.

test.bim.bootstrap assigns a no-op over that method at import time. This
conftest is loaded first, so the original classmethod can be put back while
the document-launch tests run.
"""

# Importing this module snapshots Drawing.open_with_user_command before
# test modules replace it. Skip the import outside Blender so pytest-blender
# can re-execute the suite there.
try:
    import bpy
except ImportError:
    pass
else:
    if "bonsai" not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module="bonsai")
    import test.tool.launch_original  # ruff: ignore[unused-import]
