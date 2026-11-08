---
name: blender-building-kit
description: Design and build editable modular exterior buildings in Blender using bundled Python planners and prefabs for shells, openings, awnings, rooftop equipment, trim, and pipes. Use for game assets and exterior source studies in any project.
---

# Blender Building Kit

Use the bundled kit to turn a building brief into an editable Blender assembly.
Read the [helper contract](references/helper-contract.md) for component inputs and
the [AXIOM-inspired workshop](examples/axiom_workshop.py) for a complete local
example. The planners use ordinary Python. Mesh prefabs and previews use Blender 5.

1. Establish real dimensions, the entrance and service sides, and the intended
   output. Keep the assembly in meters, with its front-left ground origin,
   frontage along −Y, and +Z up. If a destination needs a different pivot,
   transform the whole assembly at its root.
2. Plan rectangular shells and inset upper sections with `plan_building_shell`
   before creating scene data. Assign openings to the wall and floor that own
   them. Use separate roots for adjoining wings and custom geometry for other
   shapes. Use the shell prefab to keep real apertures and reusable parts.
3. Place details against the actual shell. Derive rooftop contacts from its
   roof surfaces and pass existing openings and exclusions to facade details.
   For an awning, pass every nearby door and window as a wall-frame
   `Opening(x, z, width, height)` through `protected_openings`, with the wall's
   `Facade` as `opening_facade`. Convert floor-local heights into that frame
   first. Narrow or raise the awning when the guard detects an overlap.
4. Keep the source editable. Give new prefabs fresh object and collection names,
   parent their roots once, and retain movable parts, anchors, and recipes.
   Save to a fresh output path. Keep preview staging outside the asset root.
5. Reopen the saved blend. Verify bounds, units, openings, awning and approach
   clearance, roof contacts, UV0, material roles, and hierarchy. Where used,
   compare pipe mating planes and diameters. Review an overall view and the
   affected detail. Deliver the blend and the review evidence requested.

The [README](README.md) shows how to run the example and import the kit. Preserve
your own destination's import and material rules when preparing derivatives.
