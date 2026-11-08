# Helper contract

Use the included module signatures and validators for exact options.
All examples assume `scripts/` is on the Python import path. Use
`plan_building_shell` in ordinary Python and instantiate prefabs in Blender 5.

## Shells and apertures

```python
from blender_building_kit.CityBuildingOpeningPrefabs import make_materials
from blender_building_kit.CityBuildingShell import (
    create_building_shell_prefab,
    plan_building_shell,
)

params = dict(
    width=10, depth=8, floor_height=3.2, roof="flat",
    openings=[
        dict(side="front", kind="door", x=1, z=0, width=1.2, height=2.35,
             design="full_glazed"),
        dict(side="front", kind="window", x=4, z=1, width=2, height=1.5,
             columns=2),
    ],
)
plan = plan_building_shell(**params)
materials = make_materials("Study", frame="paint", leaf="metal", panel="paint")
building = create_building_shell_prefab("Study", materials=materials, **params)
```

- Width runs along X and depth along Y. Shells start at the front-left ground
  corner. Front is −Y and up is +Z. Use floor-local Z and a zero-based
  `floor` for shell openings. Side coordinates follow the view from outside.
- Openings take `side` (`front`, `right`, `back`, `left`), `kind` (`door`
  or `window`), `x`, `z`, `width`, and `height`. Doors can take `design`
  and `leaves` (1 or 2). Windows can take `columns` and `rows`.
  `CityBuildingEntrances.DOOR_DESIGNS` supplies the valid choices.
  Use `full_glazed` for a full glass door.
- `roof` takes `flat` or `gable`. Gables use `ridge_axis="x"` or `"y"`
  and a pitch greater than 0° and below 75°. Optional `towers` contain
  uniquely named inset sections with `id`, `width`, `depth`, and a
  parent-local `offset=[x,y]`. Parents precede their children and have
  flat caps. The child roof envelope fits inside its parent's cap and clears
  siblings. The top of the parent cap sets the child base elevation.
- The five material roles are `frame`, `leaf` (door leaf or roof), `panel`
  (walls), `glass`, and `hardware`. Reuse one mapping or supply explicit
  Blender materials under the same keys.

## Awnings and facade details

The awning's `facade.origin` is its rear eave mounting point. Project the
roof, fascia, valance, and supports into the wall's facade frame to check the
whole profile. The guard in `create_canopy_prefab` does this before creating
Blender objects and persists the opening records in its recipe.

```python
from blender_building_kit.CityBuildingDetailPrefabs import create_canopy_prefab
from blender_building_kit.CityBuildingEntrances import Facade, Opening

wall = Facade(**plan["sections"][0]["wall_plan"]["facades"]["front"]["frame"])
canopy = create_canopy_prefab(
    "EntryAwning", 2.2, .8, materials,
    facade=Facade(origin=wall.point(.5, 2.8, 0), right=wall.right, up=wall.up),
    style="flat", supports="none",
    protected_openings=[Opening(1, 0, 1.2, 2.35), Opening(4, 1, 2, 1.5)],
    opening_facade=wall,
)
canopy.root.parent = building.root
```

Canopy styles are `flat`, `sloped`, `gable`, `barrel`, and `fabric`.
Supports are `brackets`, `posts`, or `none`. The canopy and opening frames
must share right and up axes. `opening_clearance` defaults to 25 mm. Use the
actual placed door/window rectangles in the wall frame, including lifted Z
offsets for upper floors. Standalone canopies can omit protected openings.

Use `facade_top_from_shell` for actual gable/eave profiles and
`create_facade_details_prefab` for panel seams, downpipes, boxes, vents, and
bollards. Supply openings and exclusions for features such as awnings and
signs. Seams clip around them and solid elements reject overlaps. Set seam
`height=None` to reach the profiled top. Use `create_building_trim_prefab`
with explicit `TrimBand` definitions for continuous mitered trim.

## Roof equipment, pipes, and sectional garage doors

- Add `rooftop_elements` to the shell with a `kind` and section-local
  `center=[x,y]`. Use `section` to target an inset section. Kinds are
  `chimney`, `hvac`, `hatch`, and `vent`. HVAC and hatches require flat
  roofs. Derive a standalone support with `roof_support_from_section`.
- A `PipePort` contains a mating-face center, outward normal, physical outer
  diameter, perpendicular up vector, and `plain` or `flanged` coupling.
  Match diameter and coupling at both ends. Use `pipe_connection_spec` to
  seat sockets against host surfaces, and route with explicit waypoints and
  room for bend take-up. Supply ports and waypoints in a common frame. Match
  socket and route segments. These parts represent visual geometry.
- `create_garage_prefab` builds a sectional opening assembly using its
  procedural panel by default. Cut the bay in the host first and verify
  clearances in both closed and open poses. A custom panel can be passed as
  an explicit recipe input.

## Recipes and exports

A shell has `CityBuildingShellRecipe`. Its `parameters` can be fed back to
`create_building_shell_prefab` with a new name and a material mapping. Details
and openings use `CityOpeningRecipe`, where `parameters.kind` identifies the
prefab; use `fabricate_prefab` to rebuild supported kinds. Roof elements add
`element_kind`. Keep portable recipes together and preserve the hierarchy
when saving. Names must be free in both object and collection data.

Keep the editable blend as the source of truth. For static FBX, work on a
separate derivative and choose the closed pose and semantic slot names first.
`CityBuildingStudyIO.checked_fbx` exports a selected static mesh and reads it
back in Blender to check dimensions, triangle count, and material slots.
Verify the resulting file with the destination's actual importer separately.
