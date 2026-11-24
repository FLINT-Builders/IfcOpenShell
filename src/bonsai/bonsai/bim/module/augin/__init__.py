# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2020, 2021 Dion Moult <dion@thinkmoult.com>
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai.  If not, see <http://www.gnu.org/licenses/>.

import bpy
from bpy.app.handlers import persistent

from . import operator, prop, ui

classes = (
    prop.AuginProperties,
    ui.BIM_PT_augin,
    operator.AuginLogin,
    operator.AuginCreateNewModel,
    operator.AuginReset,
)


@persistent
def remove_legacy_scene_credentials(*args):
    # Older versions stored credentials on the scene, which is saved to the .blend.
    for scene in bpy.data.scenes:
        scene.pop("AuginProperties", None)


def register():
    # WindowManager properties are not saved to the .blend, keeping credentials out of shared files.
    bpy.types.WindowManager.AuginProperties = bpy.props.PointerProperty(type=prop.AuginProperties)
    bpy.app.handlers.load_post.append(remove_legacy_scene_credentials)


def unregister():
    del bpy.types.WindowManager.AuginProperties
    bpy.app.handlers.load_post.remove(remove_legacy_scene_credentials)
