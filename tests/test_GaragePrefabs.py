"""Check sectional track geometry and, in Blender, editable panel prefabs.

The Blender cases use a disposable background scene and save no files.
"""
import json
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from blender_building_kit.CityGarageGeometry import sectional_pose,garage_closure


class GaragePath(unittest.TestCase):
    def test_closure_side_lap_and_continuous_return_clearance(self):
        for height,radius,lap in ((2.6,.65,.015),(3.65,.65,.015),(3.6,.16,.02)):
            r=garage_closure(2.8,height,.24,.48,radius=radius,side_overlap=lap)
            self.assertAlmostEqual(r['panel_width_m'],2.8+2*lap)
            self.assertAlmostEqual(r['track_side_clearance_m'],.027-lap)
            self.assertLess(r['frame_back_depth_m'],-.24)
            at_min=garage_closure(2.8,height,.24,r['minimum_inset_m'],radius=radius,side_overlap=lap)
            self.assertAlmostEqual(at_min['frame_back_depth_m'],-.244)
            # Independently sample the actual rotated rectangular cross-section
            # over the bend against the derived stationary return plane.
            for step in range(301):
                a=math.pi/2*step/300
                front=-.48-radius*(1-math.cos(a))+.0175*math.cos(a)+r['panel_height_m']/2*math.sin(a)
                self.assertGreaterEqual(r['frame_back_depth_m']-front,.004-1e-9)
        for options in (dict(inset=.25),dict(side_overlap=.025),dict(side_overlap=.001),dict(side_overlap=0),dict(clearance=float('nan'))):
            args=dict(width=2.8,height=2.6,wall_depth=.24,inset=.48);args.update(options)
            with self.assertRaises(ValueError):garage_closure(**args)

    def test_track_continuity_and_input_rejection(self):
        for height,count in ((2.6,24),(3.6,24),(4.8,32)):
            previous=None
            for step in range(101):
                y,z,a=sectional_pose(height,count//2,step/100,count=count)
                self.assertTrue(all(math.isfinite(v) for v in (y,z,a)))
                if previous:
                    self.assertGreaterEqual(y+1e-10,previous[0]);self.assertGreaterEqual(z+1e-10,previous[1])
                previous=(y,z,a)
        for args in ((0,0,0),(3.6,-1,0),(3.6,24,0),(3.6,0,-.1),(3.6,0,float('nan'))):
            with self.assertRaises(ValueError):sectional_pose(*args)


if '--blender' in sys.argv:
    import bpy
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from blender_building_kit.CityBuildingEntrances import Facade,Opening,create_wall
    from blender_building_kit.CityBuildingOpeningPrefabs import make_materials,fabricate_prefab,load_prefab,_Geometry
    from blender_building_kit.CityGaragePrefabs import create_garage_prefab

    class GarageMesh(unittest.TestCase):
        def test_sectional_panel_clearance_shared_mesh_and_recipe(self):
            before=[set(bpy.data.objects),set(bpy.data.meshes),set(bpy.data.collections),set(bpy.data.materials)]
            def tree(obj):
                return BVHTree.FromPolygons([obj.matrix_world@v.co for v in obj.data.vertices],
                                           [list(p.vertices) for p in obj.data.polygons])
            try:
                mats=make_materials('_GarageTest',leaf='metal',frame='paint')
                for i,(width,height) in enumerate(((2.8,2.6),(4.5,3.6),(4.5,3.65))):
                    a=math.radians(37);f=Facade((2,4,0),(math.cos(a),math.sin(a),0),(0,0,1))
                    o=Opening(0,0,width,height);prefab=create_garage_prefab('_GarageTest'+str(i),o,.24,mats,facade=f)
                    self.assertEqual(len({p.data for p in prefab.parts}),1)
                    frame=next(o for o in prefab.root.children if o.type=='MESH' and 'CityOpeningPart' not in o)
                    for face in frame.data.polygons:
                        pts=[frame.matrix_world@frame.data.vertices[v].co for v in face.vertices]
                        local=[((p-Vector(f.origin)).dot(Vector(f.right)),(p-Vector(f.origin)).dot(Vector(f.up)),(p-Vector(f.origin)).dot(Vector(f.outward))) for p in pts]
                        on_jamb=any(all(abs(p[0]-x)<1e-5 for p in local) for x in (0,width))
                        on_header=all(abs(p[1]-height)<1e-5 for p in local) and min(width,max(p[0] for p in local))-max(0,min(p[0] for p in local))>1e-5
                        if on_jamb or on_header:
                            overlap=min(0,max(p[2] for p in local))-max(-.24,min(p[2] for p in local))
                            self.assertLessEqual(overlap,1e-5,'Exposed garage frame face duplicates host-wall reveal')
                    self.assertEqual(prefab.recipe['hardware']['wall_throat_owner'],'host_wall')
                    w=_Geometry();wf=Facade(tuple(Vector(f.origin)-Vector(f.right)*.4),f.right,f.up)
                    create_wall(w,width+.8,height+1,.24,[Opening(.4,0,width,height)],facade=wf)
                    verts=[Vector(v) for face in w.faces for v in face];polys=[tuple(range(j,j+4)) for j in range(0,len(verts),4)]
                    wall=BVHTree.FromPolygons(verts,polys);original=[p.matrix_world.copy() for p in prefab.parts]
                    def side_rays(expect_hit):
                        all_trees=[wall,tree(frame),*[tree(p) for p in prefab.parts]]
                        for x,lateral in ((.005,-.25),(width-.005,.25),(.005,0),(width-.005,0),(-.005,-1),(width+.005,1)):
                            for panel in (0,12,23):
                                z=(panel+.5)*height/24
                                start=Vector(f.point(x-lateral*(.48+.1),z,.1))
                                direction=(-Vector(f.outward)+Vector(f.right)*lateral).normalized()
                                distance=(.48+.18)*math.sqrt(1+lateral*lateral)
                                hit=any(t.ray_cast(start,direction,distance)[0] is not None for t in all_trees)
                                self.assertEqual(hit,expect_hit,(i,x,lateral,panel,'side sightline'))
                    side_rays(True)
                    for step in range(51):
                        prefab.set_open(step/50);ts=[tree(p) for p in prefab.parts];ft=tree(frame)
                        for j,t in enumerate(ts):
                            self.assertFalse(t.overlap(wall),(i,step,j,'wall'))
                            self.assertFalse(t.overlap(ft),(i,step,j,'frame/track'))
                            # Nonadjacent ordered panels cannot meet on this monotone track;
                            # neighboring panels are the relevant bending/contact boundary.
                            if j:self.assertFalse(t.overlap(ts[j-1]),(i,step,j,'neighbor'))
                        lo,hi=prefab.recipe['motion_bounds_m']
                        for obj in prefab.parts:
                            for v in obj.data.vertices:
                                p=obj.matrix_world@v.co;self.assertTrue(all(lo[k]-1e-5<=p[k]<=hi[k]+1e-5 for k in range(3)))
                    load_prefab(prefab.root).set_open(0)
                    self.assertTrue(all(max(abs(x-y) for a,b in zip(p.matrix_world,m) for x,y in zip(a,b))<1e-6 for p,m in zip(prefab.parts,original)))
                    prefab.set_open(1);side_rays(False);prefab.set_open(0)
                    copy=fabricate_prefab('_GarageCopy'+str(i),prefab.recipe,mats)
                    self.assertEqual(copy.recipe['parameters'],prefab.recipe['parameters'])
            finally:
                for obj in set(bpy.data.objects)-before[0]:bpy.data.objects.remove(obj,do_unlink=True)
                for mesh in set(bpy.data.meshes)-before[1]:
                    if mesh.users==0:bpy.data.meshes.remove(mesh)
                for col in set(bpy.data.collections)-before[2]:bpy.data.collections.remove(col)
                for mat in set(bpy.data.materials)-before[3]:
                    if mat.users==0:bpy.data.materials.remove(mat)


if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]] if '--blender' in sys.argv else None,verbosity=2)
