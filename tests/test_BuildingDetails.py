"""Offline trim join/topology and canopy variation contracts. Ordinary Python;
no Blender, scene or file writes. Tests actual surfaces rather than snapshots.
"""
import math
import json
from collections import Counter
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from blender_building_kit.CityBuildingDetails import create_trim,create_canopy,TrimBand,plan_building_trim,create_building_trim,create_building_walls
from blender_building_kit.CityBuildingEntrances import Facade,Opening,create_wall,_box


class Mesh:
    def __init__(self):self.faces=[];self.slots=[];self.uvs=[]
    def face(self,points,slot,color,uv=None):self.faces.append(points);self.slots.append(slot);self.uvs.append(uv)


def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def volume(faces):
    return sum(sum(a*b for a,b in zip(f[0],cross(f[i],f[i+1])))/6 for f in faces for i in range(1,len(f)-1))


class Details(unittest.TestCase):
    def test_joined_building_walls_remove_exterior_coplanar_corner_caps(self):
        plan=plan_building_trim(8,6,2,openings={'front':[Opening(2,0,1.1,2.4)]})
        b=Mesh();result=create_building_walls(b,plan,.22,wall_slot=2,reveal_slot=0)
        height=plan['assembly_seats']['wall_top_m']
        self.assertAlmostEqual(volume(b.faces),(8*6-(8-.44)*(6-.44))*height-1.1*2.4*.22,places=7)
        planes={}
        for face,slot in zip(b.faces,b.slots):
            for axis,coord in ((0,0),(0,8),(1,0),(1,6)):
                if not all(abs(p[axis]-coord)<1e-9 for p in face):continue
                self.assertEqual(slot,2)  # reveal-colored end caps caused the visible strip
                dims=[i for i in range(3) if i!=axis]
                bounds=[(min(p[i] for p in face),max(p[i] for p in face)) for i in dims]
                for other in planes.setdefault((axis,coord),[]):
                    area=math.prod(max(0,min(a[1],c[1])-max(a[0],c[0])) for a,c in zip(bounds,other))
                    self.assertLess(area,1e-9)
                planes[(axis,coord)].append(bounds)
        self.assertTrue(all(not r['end_caps'][0] and r['miter_ends'] for r in result['facades'].values()))
        # Rotated assembly preserves volume and inverse-transformed corner fit.
        angle=math.radians(37);c=Mesh();rot=plan_building_trim(8,6,2,origin=(3,4,.5),yaw_degrees=37,openings=plan['parameters']['openings'])
        create_building_walls(c,rot,.22,wall_slot=2,reveal_slot=0)
        self.assertAlmostEqual(volume(c.faces),volume(b.faces),places=6)
        for face,other in zip(b.faces,c.faces):
            for (x,y,z),p in zip(face,other):
                expected=(3+x*math.cos(angle)-y*math.sin(angle),4+x*math.sin(angle)+y*math.cos(angle),.5+z)
                self.assertTrue(all(abs(a-b)<1e-8 for a,b in zip(p,expected)))
        for params in [dict(wall_depth=4),dict(wall_depth=.8)]:
            bad=plan_building_trim(8,6,2,openings={'left':[Opening(.6,1,1,1)]});empty=Mesh()
            with self.assertRaises(ValueError):create_building_walls(empty,bad,**params)
            self.assertFalse(empty.faces)

    def test_building_dimensions_levels_offsets_and_seating(self):
        b=Mesh();plan=create_building_trim(b,10,7,3,3.2,base_offset=.03,floor_offset=.05,roof_offset=-.04)
        for actual,expected_level in zip(plan['datums']['floor_levels_m'],[0,3.2,6.4,9.6]):
            self.assertAlmostEqual(actual,expected_level)
        self.assertEqual([p['id'] for p in plan['bands']],['base','floor_1','floor_2','roof'])
        expected=[(.03,.21),(3.19,3.31),(6.39,6.51),(9.34,9.56)]
        for band,(low,high),op in zip(plan['bands'],expected,plan['operations']):
            self.assertAlmostEqual(band['z_range_m'][0],low);self.assertAlmostEqual(band['z_range_m'][1],high)
            faces=[b.faces[i] for group in op['roles'].values() for i in group]
            profile=band['profile'];outer=profile['projection'];embed=profile['embed']
            # Exact wall seating and declared external size, without a mysterious
            # half-width correction at every callsite.
            self.assertAlmostEqual(min(p[0] for f in faces for p in f),-outer)
            self.assertAlmostEqual(max(p[0] for f in faces for p in f),10+outer)
            self.assertAlmostEqual(min(p[1] for f in faces for p in f),-outer)
            self.assertAlmostEqual(max(p[1] for f in faces for p in f),7+outer)
            area=(10+2*outer)*(7+2*outer)-(10-2*embed)*(7-2*embed)
            self.assertAlmostEqual(volume(faces),area*profile['height'],places=7)
            edges=Counter(tuple(sorted((a,c))) for f in faces for a,c in zip(f,f[1:]+f[:1]))
            self.assertTrue(all(n==2 for n in edges.values()))
        self.assertEqual(plan_building_trim(6,5,1)['datums']['floor_levels_m'],[0,3.])
        self.assertEqual([p['id'] for p in plan_building_trim(6,5,1)['bands']],['base','roof'])
        seats=plan_building_trim(6,5,2)['assembly_seats']
        self.assertAlmostEqual(seats['wall_top_m'],5.96)
        self.assertEqual(seats['roof_cap_local_bounds_m'],[[.02,.02,5.96],[5.98,4.98,6.]])
        walls=Mesh();create_wall(walls,6,seats['wall_top_m'],.22)
        self.assertLess(max(z for f in walls.faces for x,y,z in f),6)
        trim=Mesh();create_building_trim(trim,6,5,2)
        for face in trim.faces:
            if all(abs(z-6)<1e-9 for x,y,z in face):
                self.assertTrue(max(x for x,y,z in face)<=.02+1e-9 or min(x for x,y,z in face)>=5.98-1e-9 or
                                max(y for x,y,z in face)<=.02+1e-9 or min(y for x,y,z in face)>=4.98-1e-9)
        cap=Mesh();_box(cap,Facade(),(.02,5.96,5.98,6),-.02,-4.98,2)
        self.assertAlmostEqual(volume(cap.faces),5.96*4.96*.04,places=8)
        covered=plan_building_trim(8,6,2,roof_cap_thickness=4,base=None,floor=None,roof=None)
        self.assertEqual(covered['storey_opening_zones'][1]['clear_z_intervals_m'],[])

    def test_building_opening_cuts_corner_join_and_world_frames(self):
        openings={'front':[Opening(1,0,1.2,2.4),Opening(2.15,0,.6,2)],
                  'right':[Opening(1,2.8,1,1)]}
        plain=create_building_trim(Mesh(),8,6,2,openings=openings)
        b=Mesh();rot=create_building_trim(b,8,6,2,openings=openings,origin=(3,4,.5),yaw_degrees=37)
        self.assertEqual([len(x['opening_cuts_m']) for x in plain['bands']],[1,1,0])
        a=math.radians(37);frame=Facade((3,4,.5),(math.cos(a),math.sin(a),0),(-math.sin(a),math.cos(a),0))
        for op,other in zip(plain['operations'],rot['operations']):
            for (x,y,z),world in zip(op['world_centerline_m'],other['world_centerline_m']):
                self.assertTrue(all(abs(a-b)<1e-8 for a,b in zip(frame.point(x,y,z),world)))
        # The front door produces a cut with two capped ends; all other corners
        # remain in one continuous run. Its expanded opening has no front trim.
        base=next(op for op in rot['operations'] if op['band']=='base')
        self.assertFalse(base['closed']);self.assertEqual(len(base['roles']['ends']),2)
        self.assertAlmostEqual(base['points'][0][0],2.775);self.assertAlmostEqual(base['points'][-1][0],.975)
        zone=plain['storey_opening_zones'][0]['clear_z_intervals_m'][0]
        self.assertAlmostEqual(zone[0],.205);self.assertAlmostEqual(zone[1],2.915)
        local=Mesh();local_plan=create_building_trim(local,8,6,2,openings=openings)
        base=next(op for op in local_plan['operations'] if op['band']=='base')
        for face in [local.faces[i] for group in base['roles'].values() for i in group]:
            # Any face reaching the front exterior plane must stay outside the
            # union of the two doorway reservations, including25mm clearance.
            if all(y<=0 for x,y,z in face):
                self.assertTrue(max(x for x,y,z in face)<=.975+1e-8 or min(x for x,y,z in face)>=2.775-1e-8)
        front=Facade(**rot['facades']['front']['frame']);back=Facade(**rot['facades']['back']['frame'])
        self.assertEqual(front.origin,(3,4,.5))
        self.assertTrue(all(abs(a-b)<1e-8 for a,b in zip(back.origin,frame.point(8,6,0))))
        self.assertTrue(all(abs(a+b)<1e-8 for a,b in zip(front.right,back.right)))

    def test_building_roundtrip_update_and_atomic_rejection(self):
        original=plan_building_trim(8,6,2,openings={'front':[Opening(1,0,1,2.4)]})
        portable=json.loads(json.dumps(original))
        self.assertEqual(json.loads(json.dumps(plan_building_trim(**portable['parameters']))),portable)
        update=dict(portable['parameters'],width=12,depth=9,floors=4,floor_height=3.4)
        rebuilt=create_building_trim(Mesh(),**update)
        self.assertEqual([b['id'] for b in rebuilt['bands']],['base','floor_1','floor_2','floor_3','roof'])
        self.assertAlmostEqual(rebuilt['datums']['wall_height_m'],13.6)
        self.assertEqual(original['datums']['wall_height_m'],6)
        self.assertAlmostEqual(max(x for op in rebuilt['operations'] for x,y in op['points']),12.05)
        for options in [dict(floors=0),dict(floors=True),dict(floor_height=.1),dict(base_offset=-.1),
                        dict(roof_offset=.1),dict(roof_cap_thickness=7),dict(floor=TrimBand(6)),dict(base=TrimBand(.2,.1,5)),
                        dict(openings={'north':[]}),dict(openings={'front':[Opening(7.5,0,1,2)]}),
                        dict(openings={'front':[Opening(0,0,1,2)]})]:
            b=Mesh();params=dict(width=8,depth=6,floors=2)
            params.update(options)
            with self.assertRaises(ValueError):create_building_trim(b,**params)
            self.assertFalse(b.faces)

    def test_trim_shared_corner_topology_and_volume(self):
        for path,closed in [([(0,0),(3,0),(3,2)],False),([(0,0),(1.5,.8),(3,0)],False),
                            ([(0,0),(3,0),(3,2),(0,2)],True)]:
            b=Mesh();r=create_trim(b,path,width=.12,depth=.08,closed=closed)
            edges=Counter()
            for face in b.faces:
                for a,c in zip(face,face[1:]+face[:1]):edges[tuple(sorted((a,c)))]+=1
            self.assertTrue(all(n==2 for n in edges.values()))
            self.assertAlmostEqual(volume(b.faces),sum(r['lengths_m'])*.12*.08,places=8)
            self.assertEqual(len(r['roles']['ends']),0 if closed else 2)

    def test_trim_rotated_basis_and_atomic_invalid_rejection(self):
        a=math.radians(37);f=Facade((3,4,2),(math.cos(a),math.sin(a),0),(0,0,1))
        b=Mesh();c=Mesh();path=[(0,0),(2,0),(2,1)]
        create_trim(b,path);create_trim(c,path,facade=f)
        for face,other in zip(b.faces,c.faces):
            for (x,y,z),point in zip(face,other):
                self.assertTrue(all(abs(a-b)<1e-9 for a,b in zip(f.point(x,z,-y),point)))
        for path,opts in [([(0,0),(0,0)],{}), ([(0,0),(1,0),(0,0)],{}),
                          ([(0,0),(1,1),(0,1),(1,0)],{}),
                          ([(0,0),(.02,0),(.02,.02)],{'width':1}),
                          ([(0,0),(1,0),(.1,.001)],{})]:
            empty=Mesh()
            with self.assertRaises(ValueError):create_trim(empty,path,**opts)
            self.assertFalse(empty.faces)

    def test_canopy_distinct_forms_materials_and_contacts(self):
        signatures=[]
        for style in ('flat','sloped','gable','barrel','fabric'):
            for supports in ('brackets','posts','none'):
                b=Mesh();r=create_canopy(b,3.2,1.4,style=style,supports=supports)
                self.assertEqual(len(r['support_contacts']),0 if supports=='none' else 2)
                self.assertGreater(volume(b.faces),0)
                self.assertTrue(all(len(face)>=3 and all(math.isfinite(v) for p in face for v in p) for face in b.faces))
                if supports=='none':signatures.append(tuple(tuple(tuple(p) for p in face) for face in b.faces))
                if style=='fabric':self.assertIn(3,b.slots)
        self.assertEqual(len(set(signatures)),5)
        b=Mesh()
        with self.assertRaises(ValueError):create_canopy(b,3,1,style='unknown')
        self.assertFalse(b.faces)

    def test_canopy_checks_placed_openings_before_appending(self):
        wall = Facade((5, 4, 1), (0, 1, 0))
        openings = [Opening(3.1, 0, 2.3, 2.8), Opening(.8, .55, 2.1, 3.1),
                    dict(x=5.8, z=.55, width=1.6, height=3.1)]
        wide = Facade(wall.point(1.2, 3.3, .01), wall.right, wall.up)
        narrow = Facade(wall.point(3.0, 3.3, .01), wall.right, wall.up)
        b = Mesh()
        create_canopy(b, 2, 1, facade=narrow, supports='none')
        original = list(b.faces)
        with self.assertRaisesRegex(ValueError, 'protected opening 2'):
            create_canopy(b, 6, 1, facade=wide, supports='none',
                          protected_openings=openings, opening_facade=wall)
        self.assertEqual(b.faces, original)
        result = create_canopy(b, 2.5, 1, facade=narrow, supports='none',
                               protected_openings=openings, opening_facade=wall)
        self.assertEqual(sorted(i for group in result['roles'].values() for i in group),
                         list(range(len(original), len(b.faces))))
        self.assertEqual(b.faces[:len(original)], original)
        unguarded = Mesh()
        create_canopy(unguarded, 2.5, 1, facade=narrow, supports='none')
        self.assertEqual(b.faces[len(original):], unguarded.faces)
        self.assertEqual(b.slots[len(original):], unguarded.slots)
        with self.assertRaisesRegex(ValueError, 'matching right/up axes'):
            create_canopy(b, 2.5, 1, facade=narrow, protected_openings=openings, opening_facade=Facade())

    def test_canopy_checks_fascia_and_supports(self):
        fascia_opening = Opening(.5, -.14, 1, .07)
        with self.assertRaisesRegex(ValueError, 'protected opening 1'):
            create_canopy(Mesh(), 3.2, 1.5, style='flat', supports='none',
                          protected_openings=[fascia_opening])
        with self.assertRaisesRegex(ValueError, 'protected opening 1'):
            create_canopy(Mesh(), 3.2, 1.5, style='fabric', supports='none',
                          protected_openings=[Opening(.5, -.53, 1, .09)])
        side_window = Opening(.04, -.85, .24, .48)
        create_canopy(Mesh(), 3.2, 1.5, style='flat', supports='none',
                      protected_openings=[side_window])
        for supports in ('brackets', 'posts'):
            with self.subTest(supports=supports), self.assertRaisesRegex(ValueError, 'protected opening 1'):
                create_canopy(Mesh(), 3.2, 1.5, style='flat', supports=supports,
                              protected_openings=[side_window])


if '--blender' in sys.argv:
    import bpy
    from mathutils import Vector
    from blender_building_kit.CityBuildingOpeningPrefabs import make_materials,fabricate_prefab,find_assembly_anchor,load_prefab
    from blender_building_kit.CityBuildingDetailPrefabs import create_canopy_prefab,create_building_trim_prefab

    class DetailPrefabs(unittest.TestCase):
        def test_parameters_helpers_copy_and_resize(self):
            before=[set(bpy.data.objects),set(bpy.data.meshes),set(bpy.data.collections),set(bpy.data.materials)]
            try:
                mats=make_materials('_DetailTest')
                for style in ('flat','sloped','gable','barrel','fabric'):
                    canopy=create_canopy_prefab('_CanopyTest_'+style,3.2,1.5,mats,style=style)
                    clone=fabricate_prefab('_CanopyRebuild_'+style,json.loads(json.dumps(canopy.recipe)),mats)
                    self.assertEqual(clone.recipe['parameters'],canopy.recipe['parameters'])
                    self.assertEqual(find_assembly_anchor(clone.root,'FrontRight').location,Vector((3.2,-1.5,0)))
                guard = create_canopy_prefab('_CanopyGuard', 2.6, .9, mats,
                                              facade=Facade((2,0,3.15)), style='flat', supports='none',
                                              protected_openings=[Opening(4.8,.5,1.3,2.7)],
                                              opening_facade=Facade(), opening_clearance=.05)
                recipe = json.loads(json.dumps(guard.recipe))
                rebuilt = fabricate_prefab('_CanopyGuardRebuild', recipe, mats)
                self.assertEqual(rebuilt.recipe['parameters'], guard.recipe['parameters'])
                recipe['parameters']['width'] = 3.1
                with self.assertRaisesRegex(ValueError, 'protected opening 1'):
                    fabricate_prefab('_CanopyGuardInvalid', recipe, mats)
                self.assertNotIn('_CanopyGuardInvalid', bpy.data.objects)
                self.assertNotIn('_CanopyGuardInvalid', bpy.data.collections)
                trim=create_building_trim_prefab('_TrimTest',8,6,2,mats,origin=(2,3,.4),yaw_degrees=37,
                                                openings={'front':[Opening(2,0,1.1,2.4)]})
                clone=fabricate_prefab('_TrimRebuild',json.loads(json.dumps(trim.recipe)),mats)
                self.assertEqual(clone.recipe['parameters'],trim.recipe['parameters'])
                mount=find_assembly_anchor(trim.root,'Mount');floor=find_assembly_anchor(trim.root,'Floor_2')
                self.assertAlmostEqual(floor.location.z,6.4,places=6)
                self.assertLess((mount.matrix_world.to_3x3().col[0]-Vector(trim.recipe['hardware']['datums']['right'])).length,1e-6)
                # Copy/suffix rename plus root move keeps helper coordinates usable.
                copied=trim.root.copy();bpy.context.scene.collection.objects.link(copied)
                for obj in trim.root.children:
                    child=obj.copy();bpy.context.scene.collection.objects.link(child);child.parent=copied
                copied.location=(5,-3,1);bpy.context.view_layer.update();load_prefab(copied)
                anchor=find_assembly_anchor(copied,'Floor_2')
                self.assertLess((anchor.matrix_world.translation-Vector((7,0,7.4))).length,1e-6)
                recipe=json.loads(json.dumps(trim.recipe));recipe['parameters'].update(width=12,depth=9,floors=4)
                update=fabricate_prefab('_TrimUpdated',recipe,mats)
                self.assertAlmostEqual(find_assembly_anchor(update.root,'Floor_4').location.z,12.4,places=6)
                self.assertEqual(len(update.recipe['hardware']['bands']),5)
                self.assertEqual(len(trim.recipe['hardware']['bands']),3)
            finally:
                for obj in set(bpy.data.objects)-before[0]:bpy.data.objects.remove(obj,do_unlink=True)
                for mesh in set(bpy.data.meshes)-before[1]:
                    if mesh.users==0:bpy.data.meshes.remove(mesh)
                for col in set(bpy.data.collections)-before[2]:bpy.data.collections.remove(col)
                for mat in set(bpy.data.materials)-before[3]:
                    if mat.users==0:bpy.data.materials.remove(mat)


if __name__=='__main__':unittest.main(argv=[sys.argv[0]] if '--blender' in sys.argv else None,verbosity=2)
