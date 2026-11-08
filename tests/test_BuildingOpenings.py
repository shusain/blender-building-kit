"""Offline geometry contracts for reusable wall/window/door authoring.

Run with ordinary Python; no Blender, source assets or file writes. Checks actual
generated surfaces, hole area, welded topology/volume, rotated bases and atomic
rejection. Blender raycast/FBX/render evidence is separate from these contracts.
Opt-in Blender5: --background --factory-startup --disable-autoexec --python
this-file -- --blender. Adds real prefab material/motion/wall-clearance tests;
owned temporary collections/materials are removed, with no source/file saves.
"""
import math
from pathlib import Path
import sys
import unittest
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from blender_building_kit.CityBuildingEntrances import DOOR_DESIGNS, Facade, Opening, create_wall, create_window, create_door, create_entrance_hall


class Mesh:
    def __init__(self):
        self.faces, self.slots, self.colors, self.uvs = [], [], [], []

    def face(self, points, slot, color, uv=None):
        self.faces.append(points); self.slots.append(slot); self.colors.append(color); self.uvs.append(uv)


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def sub(a, b):
    return tuple(x-y for x,y in zip(a,b))


def area(face):
    return sum(math.sqrt(sum(v*v for v in cross(sub(face[i],face[0]),sub(face[i+1],face[0]))))/2
               for i in range(1,len(face)-1))


class Openings(unittest.TestCase):
    def test_entrance_hall_clear_floor_hidden_endpoint_and_transformed_basis(self):
        opening=Opening(2,0,1.1833333334,1.91475);b=Mesh()
        hall=create_entrance_hall(b,opening,.22)
        self.assertEqual(len(b.faces),10)
        floors=[b.faces[i] for i in hall['roles']['floor']]
        self.assertAlmostEqual(sum(area(face) for face in floors),opening.width*.22+1.4*2.38+1.6*1.2)
        for face in floors:self.assertGreater(cross(sub(face[1],face[0]),sub(face[2],face[0]))[2],0)
        for i in hall['roles']['ceiling']:self.assertLess(cross(sub(b.faces[i][1],b.faces[i][0]),sub(b.faces[i][2],b.faces[i][0]))[2],0)
        for i,a in enumerate(hall['floor_regions_m']):
            for c in hall['floor_regions_m'][:i]:
                self.assertLessEqual(max(0,min(a[2],c[2])-max(a[0],c[0]))*max(0,min(a[3],c[3])-max(a[1],c[1])),1e-9)
        self.assertGreater(hall['hide_shadow_margin_m'],.025)
        # Every point in the endpoint's radius envelope, viewed through any
        # mouth point, crosses the return panel beyond its inside edge.
        center=opening.x+opening.width/2;end=hall['anchors']['Hidden'];params=hall['parameters']
        for mouth in (-opening.width/2,0,opening.width/2):
            for dx in (-.25,.25):
                for dy in (-.25,.25):
                    hit=mouth+(end[0]-center+dx-mouth)*1.4/(end[1]+dy)
                    self.assertGreater(hit,.7)
        angle=math.radians(37);f=Facade((3,4,.5),(math.cos(angle),math.sin(angle),0))
        transformed=Mesh();rot=create_entrance_hall(transformed,opening,.22,facade=f,turn='left')
        for a,c in zip(b.faces,transformed.faces):
            for p,q in zip(reversed(a),c):
                x=2*center-p[0];y=p[1]
                expected=(3+x*math.cos(angle)-y*math.sin(angle),4+x*math.sin(angle)+y*math.cos(angle),.5+p[2])
                self.assertTrue(all(abs(v-w)<1e-8 for v,w in zip(expected,q)))
        self.assertEqual(rot['lifecycle'],hall['lifecycle'])
        for options in (dict(wing=.5),dict(depth=1.6),dict(width=.4),dict(agent_height=2.1),dict(turn='back'),dict(wall_depth=2),dict(frame_width=.4)):
            empty=Mesh();args=dict(wall_depth=.22);args.update(options)
            with self.assertRaises(ValueError):create_entrance_hall(empty,opening,**args)
            self.assertFalse(empty.faces)

    def test_actual_wall_holes_topology_and_volume(self):
        b = Mesh(); openings = [Opening(1,0,1,2.1),Opening(3,1,2,1.3)]
        report = create_wall(b,7,3,.2,openings)
        self.assertAlmostEqual(sum(area(b.faces[i]) for i in report['roles']['front']),21-2.1-2.6)
        edges = Counter(); directions = Counter(); volume = 0
        for face in b.faces:
            self.assertGreater(area(face),0)
            for a,c in zip(face,face[1:]+face[:1]):
                edge = tuple(sorted((a,c))); edges[edge]+=1; directions[edge]+=1 if a<c else -1
            for i in range(1,len(face)-1):
                volume+=sum(x*y for x,y in zip(face[0],cross(face[i],face[i+1])))/6
        self.assertTrue(all(count==2 for count in edges.values()))
        self.assertTrue(all(count==0 for count in directions.values()))
        self.assertAlmostEqual(volume,(21-2.1-2.6)*.2)

    def test_rotated_window_basis_and_fit(self):
        a=math.radians(37); f=Facade((4,8,2),(math.cos(a),math.sin(a),0),(0,0,1))
        o=Opening(1,1,2,1.4); base=Mesh();rotated=Mesh()
        report=create_window(base,o,.2,columns=3,rows=2)
        rr=create_window(rotated,o,.2,columns=3,rows=2,facade=f)
        self.assertEqual(report['roles'],rr['roles'])
        for face,other in zip(base.faces,rotated.faces):
            for (x,y,z),p in zip(face,other):
                expected=f.point(x,z,-y)
                self.assertTrue(all(abs(v-w)<1e-10 for v,w in zip(expected,p)))
        for actual,expected in zip(report['pane_bounds'],(1.065,1.065,2.935,2.335)):
            self.assertAlmostEqual(actual,expected)
        self.assertTrue(all(base.colors[i][3]==0 for i in report['roles']['glass']))
        self.assertTrue(all(area(face)>0 for face in rotated.faces))
        # No positive-area coplanar overlap between visible rail/grid fronts.
        fronts = [face for face,slot in zip(base.faces,base.slots)
                  if slot==1 and all(abs(p[1]+.02)<1e-10 for p in face)]
        for i,face in enumerate(fronts):
            for other in fronts[:i]:
                spans = [min(max(p[k] for p in face),max(p[k] for p in other))-
                         max(min(p[k] for p in face),min(p[k] for p in other)) for k in (0,2)]
                self.assertLessEqual(min(spans),1e-10)
        for face,slot in zip(base.faces,base.slots):
            if slot==1:
                # Pane front/back must not share a depth plane with opaque bar caps.
                for depth in (.02-.04,.02-.04-.006):
                    self.assertFalse(all(abs(p[1]+depth)<1e-10 for p in face))

    def test_single_double_solid_and_glazed_doors(self):
        for leaves in (1,2):
            for glazed in (False,True):
                b=Mesh();r=create_door(b,Opening(1,0,2.2,2.4),.2,leaves=leaves,glazed=glazed)
                self.assertEqual(len(r['leaves']),leaves)
                self.assertNotIn('bottom',r['roles'])
                self.assertTrue(all(area(face)>0 for face in b.faces))
                for leaf in r['leaves']:
                    self.assertGreater(leaf['bounds'][1],0)
                    self.assertEqual('glass' in leaf['roles'],glazed)

    def test_door_design_material_roles_and_true_glazing(self):
        for design in ('flush','panelled','six_panel','half_glazed','arched_glazed','full_glazed'):
            b=Mesh();r=create_door(b,Opening(1,0,1.2,2.4),.2,design=design,
                                  frame_slot=0,leaf_slot=1,panel_slot=2,glass_slot=3)
            self.assertTrue(all(b.slots[i]==0 for ids in r['roles'].values() for i in ids))
            leaf=r['leaves'][0]['roles']
            self.assertEqual('glass' in leaf,design in ('half_glazed','arched_glazed','full_glazed'))
            for i in leaf.get('glass',[]):
                self.assertEqual((b.slots[i],b.colors[i][3]),(3,0))
            for key in ('lower_panel','upper_panel'):
                self.assertTrue(all(b.slots[i]==2 for i in leaf.get(key,[])))
            # A half-glazed design has no large solid face across the upper pane.
            if design in ('half_glazed','arched_glazed'):
                pane=b.faces[leaf['glass'][1]];cx=sum(p[0] for p in pane)/len(pane);cz=sum(p[2] for p in pane)/len(pane)
                covering=[f for f,s in zip(b.faces,b.slots) if s!=3 and
                          min(p[0] for p in f)<cx<max(p[0] for p in f) and
                          min(p[2] for p in f)<cz<max(p[2] for p in f)]
                self.assertFalse(covering)
            self.assertTrue(all(area(face)>1e-10 for face in b.faces))
            if design=='six_panel':
                self.assertEqual(len([key for key in leaf if key.startswith('panel_')]),6)

    def test_glazed_alias_rejection_explains_exact_design_choices(self):
        b=Mesh()
        with self.assertRaises(ValueError) as error:
            create_door(b,Opening(1,0,1.2,2.4),.2,design='glazed')
        self.assertIn("'glazed'",str(error.exception))
        for design in DOOR_DESIGNS:
            self.assertIn(design,str(error.exception))
        self.assertFalse(b.faces)
        # The older low-level boolean remains a valid distinct API.
        report=create_door(b,Opening(1,0,1.2,2.4),.2,glazed=True)
        self.assertIn('glass',report['leaves'][0]['roles'])

    def test_invalid_inputs_leave_builder_unchanged(self):
        b=Mesh();o=Opening(1,1,1,1)
        cases=[lambda:create_wall(b,4,3,.2,[o,o]),
               lambda:create_wall(b,4,3,.2,[Opening(0,1,1,1)]),
               lambda:create_window(b,o,.2,frame_width=.6),
               lambda:create_window(b,o,.2,overlap=.2),
               lambda:create_window(b,o,.2,columns=3,mullion_width=.9),
               lambda:create_window(b,o,.2,glass_recess=.3),
               lambda:create_door(b,o,.2,leaves=3),
               lambda:create_door(b,o,.2,threshold_height=2),
               lambda:create_door(b,o,.2,glazed=True,leaf_thickness=.005),
               lambda:create_door(b,o,.2,leaf_slot=-1)]
        cases += [lambda:create_door(b,o,.2,design='unknown'),
                  lambda:create_door(b,o,.2,design='half_glazed',panel_slot=-1)]
        for operation in cases:
            with self.assertRaises(ValueError):operation()
            self.assertFalse(b.faces)
        for args in ({'right':(2,0,0)}, {'right':(0,0,1)}, {'up':(0,0,float('nan'))}):
            with self.assertRaises(ValueError):Facade(**args)


if '--blender' in sys.argv:
    import bpy
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from blender_building_kit.CityBuildingOpeningPrefabs import (
        make_materials,create_door_prefab,create_window_prefab,load_prefab,fabricate_prefab,
    )

    class Prefabs(unittest.TestCase):
        def test_material_motion_clearance_and_reuse(self):
            original_objects=set(bpy.data.objects);original_meshes=set(bpy.data.meshes)
            original_materials=set(bpy.data.materials);original_collections=set(bpy.data.collections)
            def tree(obj):
                return BVHTree.FromPolygons([obj.matrix_world@v.co for v in obj.data.vertices],
                                            [list(p.vertices) for p in obj.data.polygons])
            try:
                wood=make_materials('_OpeningTestWood',leaf='wood',frame='wood')
                metal=make_materials('_OpeningTestMetal',leaf='metal',frame='metal')
                self.assertEqual(wood['leaf'].node_tree.nodes.get('Principled BSDF').inputs['Metallic'].default_value,0)
                self.assertEqual(metal['leaf'].node_tree.nodes.get('Principled BSDF').inputs['Metallic'].default_value,1)
                self.assertEqual(wood['glass'].node_tree.nodes.get('Principled BSDF').inputs['Transmission Weight'].default_value,1)
                configs=[('door',dict(design='panelled')),('door',dict(design='half_glazed',hinge='right')),
                         ('door',dict(design='flush')),('door',dict(design='full_glazed',leaves=2)),
                         ('door',dict(design='half_glazed',motion='slide',leaves=2)),
                         ('door',dict(design='full_glazed',motion='slide',leaves=2,handles=False)),
                         ('door',dict(design='arched_glazed')),('door',dict(design='six_panel')),
                         ('window',dict(motion='fixed')),('window',dict(motion='swing',leaves=2)),
                         ('window',dict(motion='awning')),('window',dict(motion='slide',leaves=2))]
                for i,(kind,options) in enumerate(configs):
                    angle=math.radians(37);f=Facade((3,4,2),(math.cos(angle),math.sin(angle),0),(0,0,1))
                    o=Opening(0,0 if kind=='door' else .6,2.4,2.4 if kind=='door' else 1.5)
                    constructor=create_door_prefab if kind=='door' else create_window_prefab
                    prefab=constructor('_OpeningTest'+str(i),o,.24,wood if i%2==0 else metal,facade=f,**options)
                    frame=next(c for c in prefab.root.children if c.type=='MESH' and 'CityOpeningPart' not in c)
                    wall=Mesh();wf=Facade(tuple(Vector(f.origin)-Vector(f.right)*.5),f.right,f.up)
                    create_wall(wall,o.width+1,o.z+o.height+.4,.24,[Opening(.5,o.z,o.width,o.height)],facade=wf)
                    verts=[Vector(v) for face in wall.faces for v in face]
                    polys=[tuple(range(i,i+4)) for i in range(0,len(verts),4)]
                    wall_tree=BVHTree.FromPolygons(verts,polys)
                    original=[[obj.matrix_world@v.co for v in obj.data.vertices] for obj in prefab.parts]
                    def local(vertex):
                        delta=vertex-Vector(f.origin)
                        return (delta.dot(Vector(f.right)),delta.dot(Vector(f.up)),delta.dot(Vector(f.outward)))
                    for obj,part in zip(prefab.parts,prefab.recipe['parts']):
                        def role_points(role):
                            return [local(obj.matrix_world@obj.data.vertices[v].co)
                                    for index in part['roles'].get(role,[]) for v in obj.data.polygons[index].vertices]
                        if options.get('design') in ('half_glazed','arched_glazed'):
                            handle=role_points('handle_plate')+role_points('handle_grip');glass=role_points('glass')
                            self.assertGreater(min(p[1] for p in glass)-max(p[1] for p in handle),.02)
                        if kind=='door' and options.get('motion')=='slide':
                            hangers=role_points('hangers')
                            self.assertTrue(hangers)
                            rail_low,rail_high=prefab.recipe['hardware']['rail_z']
                            self.assertGreater(max(p[1] for p in hangers),rail_high)
                            self.assertLess(min(p[1] for p in hangers),o.z+o.height-.09)
                            self.assertLess(min(p[2] for p in hangers),.04)
                            self.assertGreater(max(p[2] for p in hangers),.09)
                        if kind=='window' and options.get('motion')=='slide':
                            verts=[local(obj.matrix_world@v.co) for v in obj.data.vertices]
                            low,high=min(p[1] for p in verts),max(p[1] for p in verts)
                            hardware=prefab.recipe['hardware']
                            self.assertGreater(hardware['lower_lip_z'][1]-low,.015)
                            self.assertGreater(high-hardware['upper_lip_z'][0],.015)
                            # Sash thickness fits between actual channel divider/lips.
                            back,front=min(p[2] for p in verts),max(p[2] for p in verts)
                            lips=hardware['lip_depths']
                            self.assertTrue(any(a[1]<back and front<c[0] for a,c in zip(lips,lips[1:])))
                    for step in range(21):
                        prefab.set_open(step/20);part_trees=[tree(obj) for obj in prefab.parts]
                        for j,pt in enumerate(part_trees):
                            self.assertFalse(pt.overlap(tree(frame)),(i,step,'frame'))
                            self.assertFalse(pt.overlap(wall_tree),(i,step,'wall'))
                            for other in part_trees[:j]:self.assertFalse(pt.overlap(other),(i,step,'leaves'))
                        lo,hi=prefab.recipe['motion_bounds_m']
                        for obj in prefab.parts:
                            for v in obj.data.vertices:
                                p=obj.matrix_world@v.co
                                self.assertTrue(all(lo[k]-1e-5<=p[k]<=hi[k]+1e-5 for k in range(3)))
                    load_prefab(prefab.root).set_open(0)
                    for obj,points in zip(prefab.parts,original):
                        self.assertLess(max((obj.matrix_world@v.co-p).length for v,p in zip(obj.data.vertices,points)),1e-6)
                    before=len(bpy.data.objects)
                    with self.assertRaises(ValueError):constructor(prefab.root.name,o,.24,wood,**options)
                    self.assertEqual(len(bpy.data.objects),before)
                # Suffix-renamed child objects still resolve after a prefab copy.
                copied=prefab.root.copy();bpy.context.scene.collection.objects.link(copied)
                for obj in prefab.root.children:
                    child=obj.copy();bpy.context.scene.collection.objects.link(child);child.parent=copied
                copied.location=(50,0,0);load_prefab(copied).set_open(.5)
                self.assertEqual(prefab.root['openness'],0)
                rebuilt=fabricate_prefab('_OpeningTestRebuilt',prefab.recipe,metal)
                self.assertEqual(rebuilt.recipe['parameters'],prefab.recipe['parameters'])
                self.assertEqual([len(p.data.polygons) for p in rebuilt.parts],
                                 [len(p.data.polygons) for p in prefab.parts])
            finally:
                for obj in set(bpy.data.objects)-original_objects:bpy.data.objects.remove(obj,do_unlink=True)
                for col in set(bpy.data.collections)-original_collections:bpy.data.collections.remove(col)
                for mesh in set(bpy.data.meshes)-original_meshes:
                    if mesh.users==0:bpy.data.meshes.remove(mesh)
                for material in set(bpy.data.materials)-original_materials:
                    if material.users==0:bpy.data.materials.remove(material)


if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]] if '--blender' in sys.argv else None,verbosity=2)
