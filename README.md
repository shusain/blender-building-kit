# Blender Building Kit

A standalone Codex skill and Python kit for composing editable exterior
buildings. It ships with its helpers, a local API guide, and an AXIOM-inspired
workshop you can generate from scratch. Authoring needs Blender 5, with 5.0.1
used for verification. Planning and geometry tests use ordinary Python 3.11+.
The kit uses the standard library and Blender's bundled modules.

## Try the workshop

From this directory, run the command below. Substitute your Blender executable
path if `blender` is outside your shell's PATH.

```sh
blender --background --factory-startup --python-exit-code 1 --python examples/axiom_workshop.py -- --output Artifacts/axiom
```

Choose a new output directory on each run. The example creates
`workshop.blend`, `recipes.json`, and `preview.png`. The building has real
door and window apertures, an inset gabled lab, rooftop equipment, a
clearance-checked awning, a trimmed facade, and matching pipe sockets. All
geometry and materials are built locally.

## Use it in a project

- **Codex.** Put this whole folder under your Codex skills directory as
  `blender-building-kit` or link it there, then invoke `$blender-building-kit`.
- **Blender Python.** Add the kit's `scripts/` directory to your authoring
  script's import path and import from `blender_building_kit`. Use the
  [helper contract](references/helper-contract.md) and
  [workshop script](examples/axiom_workshop.py) as references.

```python
from blender_building_kit.CityBuildingShell import plan_building_shell

plan = plan_building_shell(12, 8, floor_height=3.2, roof="gable", roof_pitch=28)
```

The helpers support rectangular shells and inset stacks. Complex footprints,
interiors, structural analysis, and engine-specific integration require their
own workflow.

## Run checks

```sh
python -m unittest discover -s tests
blender --background --factory-startup --python-exit-code 1 --python tests/test_BuildingDetails.py -- --blender
blender --background --factory-startup --python-exit-code 1 --python tests/test_BuildingOpenings.py -- --blender
blender --background --factory-startup --python-exit-code 1 --python tests/test_GaragePrefabs.py -- --blender
```

## Source and license

The kit vendors 11 original CitySimVR Blender helper modules at source revision
`d1ff1d1be97a9c135b8590b00d75878f3720ed32`, including the canopy guard from
CitySimVR #1109. The modules use package-relative imports here. The focused
upstream tests use the local package and omit two cases that require a
CitySim-specific station fixture or retrofit helper. The procedural example
adapts the AXIOM Robotics v2 massing and component placement from CitySimVR
#989. It ships as Python source.

The standalone kit is licensed under the [MIT License](LICENSE).
