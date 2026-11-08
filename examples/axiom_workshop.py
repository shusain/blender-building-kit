"""Build an AXIOM-inspired exterior in Blender 5 and save a blend, recipes, and preview.

Run in a fresh background Blender process. Outputs go to a new directory supplied
with --output. The example uses only procedural geometry and materials.
"""
import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from blender_building_kit.CityBuildingDetailPrefabs import (
    create_building_trim_prefab, create_canopy_prefab,
)
from blender_building_kit.CityBuildingDetails import TrimBand
from blender_building_kit.CityBuildingEntrances import Facade, Opening
from blender_building_kit.CityBuildingFacadeDetails import (
    create_facade_details_prefab, facade_top_from_shell,
)
from blender_building_kit.CityBuildingOpeningPrefabs import make_materials
from blender_building_kit.CityBuildingPipes import (
    PipePort, create_pipe_route_prefab, create_pipe_socket_prefab, pipe_connection_spec,
)
from blender_building_kit.CityBuildingShell import create_building_shell_prefab, plan_building_shell


def build_workshop():
    """Create an editable high-bay workshop with an inset lab and service pipe."""
    base_openings = [
        dict(side="front", kind="door", x=2, z=0, width=1.4, height=2.4, design="full_glazed"),
        dict(side="front", kind="window", x=5, z=1.5, width=4.6, height=1.6, columns=3),
        dict(side="front", kind="door", x=12, z=0, width=4, height=3.5, design="panelled", leaves=2),
        dict(side="left", kind="window", x=3, z=1.7, width=4, height=1.4, columns=3),
        dict(side="back", kind="window", x=3, z=1.6, width=5, height=1.5, columns=4),
    ]
    lab_openings = [
        dict(side=side, kind="window", x=1, z=.8, width=5.8, height=1.7, columns=4)
        for side in ("front", "right", "back")
    ]
    parameters = dict(
        width=20, depth=16, floor_height=5, roof="flat", roof_thickness=.16,
        overhang=.25, openings=base_openings,
        towers=[
            dict(id="Lab", width=8, depth=8, offset=[2, 5], floor_height=3.2,
                 roof="gable", roof_pitch=18, ridge_axis="y", overhang=.25, openings=lab_openings),
        ],
        rooftop_elements=[
            dict(id="HVAC", kind="hvac", center=[15, 11]),
            dict(id="Hatch", kind="hatch", center=[16, 5]),
            dict(id="Vent", kind="vent", section="Lab", center=[5.5, 4]),
        ],
    )
    plan = plan_building_shell(**parameters)
    materials = make_materials("Workshop", frame="metal", leaf="metal", panel="paint")
    for role, color in {"frame": (.09, .13, .17), "leaf": (.12, .18, .23),
                        "panel": (.47, .57, .66), "hardware": (.82, .32, .06)}.items():
        rgba = (*color, 1)
        material = materials[role]
        material.diffuse_color = rgba
        shader = material.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Base Color"].default_value = rgba

    building = create_building_shell_prefab("Workshop", materials=materials, **parameters)
    openings_by_side = {side: [] for side in ("front", "right", "back", "left")}
    for item in base_openings:
        openings_by_side[item["side"]].append(
            Opening(item["x"], item["z"], item["width"], item["height"])
        )
    front = Facade(**plan["sections"][0]["wall_plan"]["facades"]["front"]["frame"])
    canopy = create_canopy_prefab(
        "EntryCanopy", 2.4, 1.0, materials,
        facade=Facade(origin=front.point(1.5, 3, 0), right=front.right, up=front.up),
        style="flat", supports="none",
        protected_openings=openings_by_side["front"], opening_facade=front,
    )
    trim = create_building_trim_prefab(
        "FoundationTrim", 20, 16, 1, materials, floor_height=5,
        base=TrimBand(height=.22, projection=.06), floor=None, roof=None,
        roof_cap_thickness=0, openings=openings_by_side,
    )
    profile = facade_top_from_shell(plan, "front", projection=.025)
    details = create_facade_details_prefab(
        "FrontDetails", profile["width"], profile["height"],
        [
            dict(id="Joints", kind="panel_seams", spacing=2, height=None, width=.025, depth=.015),
            dict(id="GuardLeft", kind="bollard", x=11.4),
            dict(id="GuardRight", kind="bollard", x=16.6),
        ],
        materials, facade=front, top_profile=profile["top_profile"],
        openings=openings_by_side["front"], exclusions=[dict(x=1.5, z=2.7, width=2.4, height=.6)],
    )

    # The socket backs sit on the right wall and the cabinet's near face.
    bpy.ops.mesh.primitive_cube_add(size=1, location=(23, 11, 1.05))
    cabinet = bpy.context.object
    cabinet.name = "Service Cabinet"
    cabinet.dimensions = (1.8, 2.8, 2.1)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    cabinet.data.materials.append(materials["panel"])
    cabinet.parent = building.root
    diameter = .22
    setback = pipe_connection_spec(diameter)["socket_back"]
    wall_port = PipePort((20 + setback, 11, 1.2), (1, 0, 0), diameter)
    cabinet_port = PipePort((22.1 - setback, 11, 1.2), (-1, 0, 0), diameter)
    sockets = [
        create_pipe_socket_prefab("WallSocket", wall_port, materials),
        create_pipe_socket_prefab("CabinetSocket", cabinet_port, materials),
    ]
    pipe = create_pipe_route_prefab(
        "CoolantTransfer", wall_port, cabinet_port,
        [wall_port.position, cabinet_port.position], materials,
    )
    for prefab in (canopy, trim, details, *sockets, pipe):
        prefab.root.parent = building.root
    return {
        "building": building.recipe,
        "details": [prefab.recipe for prefab in (canopy, trim, details, *sockets, pipe)],
    }


def setup_preview(scene):
    """Set up a review camera and lighting outside the asset hierarchy."""
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, -.01))
    bpy.context.object.name = "Presentation Ground"

    target = Vector((11, 7, 3))
    bpy.ops.object.camera_add(location=(36, -37, 27))
    camera = bpy.context.object
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 33
    scene.camera = camera

    bpy.ops.object.light_add(type="SUN", rotation=(.55, -.6, -.45))
    bpy.context.object.data.energy = 2.5
    bpy.context.object.data.angle = .15
    scene.world = bpy.data.worlds.new("Preview World")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (.38, .45, .57, 1)
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = .55
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 12
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 800
    scene.render.resolution_y = 600
    scene.render.resolution_percentage = 100


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="A new output directory")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    if not bpy.app.background or bpy.data.filepath:
        parser.error("Use a fresh background Blender process without a blend file argument.")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    recipes = build_workshop()
    setup_preview(scene)

    (output / "recipes.json").write_text(json.dumps(recipes, indent=2) + "\n", encoding="utf-8")
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = "//preview.png"
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "workshop.blend"))
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()
