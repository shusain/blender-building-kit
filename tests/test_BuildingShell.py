"""Offline exterior-shell geometry contracts; ordinary Python, no file/scene writes.

Checks physical volumes, exposed cap area, aperture ownership, shared ridge/end
planes, stacked datums and rejection without caller mutation. Blender hierarchy
and checked export are exercised separately with actual Blender source evidence.
"""
from collections import Counter
import json
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from blender_building_kit.CityBuildingShell import plan_building_shell,create_building_shell,_Geometry


def cross(a,b):
    return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])


def volume(faces):
    return sum(sum(a*b for a,b in zip(f[0],cross(f[i],f[i+1])))/6
               for f in faces for i in range(1,len(f)-1))


def group_faces(b,report,name):
    return [b.faces[i] for group in report['components'] if group['id']==name for i in group['faces']]


class Shell(unittest.TestCase):
    def test_walls_reuse_real_apertures_with_storey_local_placement(self):
        b=_Geometry()
        report=create_building_shell(b,10,8,floors=3,openings=[
            dict(side='front',kind='door',x=1,z=0,width=1.1,height=2.2),
            dict(floor=2,side='back',kind='window',x=2,z=.8,width=1.5,height=1.4,columns=2)])
        faces=group_faces(b,report,'base_Walls')
        self.assertAlmostEqual(volume(faces),(80-9.56*7.56)*9-(1.1*2.2+1.5*1.4)*.22,places=7)
        self.assertEqual(report['openings'][1]['opening']['z'],6.8)
        self.assertEqual(report['plan']['sections'][0]['floor_levels_m'],[0,3,6,9])
        # No front facade polygon covers a point strictly inside the rough door.
        for face in faces:
            if all(abs(p[1])<1e-9 for p in face):
                self.assertFalse(min(p[0] for p in face)<1.55<max(p[0] for p in face) and
                                 min(p[2] for p in face)<1<max(p[2] for p in face))
        self.assertTrue(any(color[3]==0 for color in b.colors))
        self.assertEqual(set(b.slots),{0,1,2,3})

    def test_shell_glazed_door_contract_and_atomic_alias_rejection(self):
        hole=dict(side='front',kind='door',x=1,z=0,width=1.2,height=2.35)
        b=_Geometry()
        with self.assertRaisesRegex(ValueError,"Unknown door design 'glazed'.*full_glazed"):
            create_building_shell(b,10,8,openings=[dict(hole,design='glazed')])
        self.assertEqual(b.faces,[])
        report=create_building_shell(b,10,8,openings=[dict(hole,design='full_glazed')])
        self.assertEqual(report['plan']['parameters']['openings'][0]['design'],'full_glazed')
        self.assertTrue(any(color[3]==0 for color in b.colors))
        # A low-level keyword must not leak into the portable shell schema.
        with self.assertRaisesRegex(ValueError,'Opening contains unsupported fields'):
            plan_building_shell(10,8,openings=[dict(hole,glazed=True)])

    def test_roof_volume_winding_and_exact_shared_ridge_both_axes(self):
        for axis in ('x','y'):
            for pitch in (12,30,60):
                b=_Geometry()
                r=create_building_shell(b,10,8,ridge_axis=axis,roof_pitch=pitch)
                roof=group_faces(b,r,'base_GableRoof')
                self.assertAlmostEqual(volume(roof),10.6*8.6*.16,places=7)
                edges=Counter(tuple(sorted((a,c))) for f in roof for a,c in zip(f,f[1:]+f[:1]))
                self.assertTrue(all(n==2 for n in edges.values()))
                # End wall apex coincides with the underside ridge, not roof TOP.
                cross_span=10 if axis=='y' else 8
                apex=3+math.tan(math.radians(pitch))*cross_span/2
                for side in (('front','back') if axis=='y' else ('right','left')):
                    gable=group_faces(b,r,'base_Gable_'+side)
                    self.assertAlmostEqual(max(p[2] for f in gable for p in f),apex)
                    self.assertAlmostEqual(volume(gable),cross_span*(apex-3)*.22/2,places=7)
                    exterior=[p for f in gable for p in f if abs(p[2]-apex)<1e-9]
                    self.assertTrue(all(abs(p[0]-5)<1e-9 for p in exterior) if axis=='y' else
                                    all(abs(p[1]-4)<1e-9 for p in exterior))
                self.assertAlmostEqual(r['plan']['sections'][0]['roof_top_m'],apex+.16)

    def test_flat_cap_area_volume_and_no_internal_cell_sidefaces(self):
        b=_Geometry()
        r=create_building_shell(b,20,14,roof='flat',overhang=0,towers=[
            dict(id='gable',offset=[1,1],width=6,depth=8,floors=3),
            dict(id='flat',offset=[11,2],width=7,depth=9,roof='flat')])
        section=r['plan']['sections'][0]
        cap=group_faces(b,r,'base_FlatRoof')
        expected=20*14-6*8-7*9
        self.assertAlmostEqual(volume(cap),expected*.16,places=7)
        top=[f for f in cap if all(abs(p[2]-3.16)<1e-9 for p in f)]
        area=sum((max(p[0] for p in f)-min(p[0] for p in f))*(max(p[1] for p in f)-min(p[1] for p in f)) for f in top)
        self.assertAlmostEqual(area,expected)
        for child in r['plan']['sections'][1:]:
            x0,y0,x1,y1=child['footprint_m']
            for face in top:
                intersect=max(0,min(x1,max(p[0] for p in face))-max(x0,min(p[0] for p in face)))*max(0,min(y1,max(p[1] for p in face))-max(y0,min(p[1] for p in face)))
                self.assertEqual(intersect,0)
        edges=Counter(tuple(sorted((a,c))) for f in cap for a,c in zip(f,f[1:]+f[:1]))
        self.assertTrue(all(n==2 for n in edges.values()))
        self.assertEqual(section['wall_top_m'],3)

    def test_nested_stacks_accumulate_parent_cap_datums(self):
        b=_Geometry()
        r=create_building_shell(b,20,16,floors=2,floor_height=3.2,roof='flat',roof_thickness=.2,towers=[
            dict(id='middle',offset=[2,2],width=14,depth=10,floors=2,roof='flat',floor_height=3.,roof_thickness=.3),
            dict(id='top',parent='middle',offset=[2,2],width=6,depth=5,floors=1,roof='gable')])
        base,middle,top=r['plan']['sections']
        for actual,expected in zip(middle['origin_m'],[2,2,6.6]):
            self.assertAlmostEqual(actual,expected)
        for actual,expected in zip(top['origin_m'],[4,4,12.9]):
            self.assertAlmostEqual(actual,expected)
        for actual,expected in zip(top['floor_levels_m'],[12.9,16.1]):
            self.assertAlmostEqual(actual,expected)
        for section in (middle,top):
            faces=group_faces(b,r,section['id']+'_Walls')
            self.assertAlmostEqual(min(p[2] for f in faces for p in f),section['origin_m'][2])

    def test_portable_recipe_rebuild_and_no_input_mutation(self):
        towers=[dict(id='tower',offset=[2,2],width=6,depth=4,openings=[
            dict(side='right',kind='window',x=1,z=1,width=1,height=1)])]
        before=json.dumps(towers)
        plan=plan_building_shell(14,10,roof='flat',towers=towers)
        decoded=json.loads(json.dumps(plan))
        rebuilt=plan_building_shell(**decoded['parameters'])
        self.assertEqual(json.loads(json.dumps(rebuilt)),decoded)
        self.assertEqual(json.dumps(towers),before)

    def test_appending_face_groups_reference_absolute_caller_indices(self):
        b=_Geometry()
        b.face([(0,0,-1),(1,0,-1),(0,1,-1)],4,(1,1,1,1),[(0,0)]*3)
        r=create_building_shell(b,6,5)
        self.assertEqual(sorted(i for g in r['components'] for i in g['faces']),list(range(1,len(b.faces))))
        self.assertTrue(all(uv is not None and len(uv)==len(face) for uv,face in zip(b.uvs,b.faces)))

    def test_invalid_specifications_leave_caller_geometry_untouched(self):
        cases=[dict(floors=True),dict(floors=0),dict(width=float('nan')),dict(depth=-1),
               dict(wall_depth=4),dict(roof='hip'),dict(roof_pitch=90),dict(roof_pitch=True),
               dict(roof_thickness=0),dict(overhang=100),dict(ridge_axis='z'),
               dict(towers=[dict(id='tower',width=2,depth=2,offset=[1,1])]), # base is gable
               dict(roof='flat',towers=[dict(id='base',width=2,depth=2,offset=[1,1])]),
               dict(roof='flat',towers=[dict(id='tower',parent='missing',width=2,depth=2,offset=[1,1])]),
               dict(roof='flat',towers=[dict(id='tower',width=2,depth=2,offset=[0,1])]),
               dict(roof='flat',towers=[dict(id='a',width=3,depth=3,offset=[1,1]),dict(id='b',width=3,depth=3,offset=[3,2])]),
               dict(openings=[dict(side='front',kind='door',x=1,z=0,width=1,height=3)]),
               dict(openings=[dict(floor=1,side='front',kind='window',x=1,z=1,width=1,height=1)]),
               dict(openings=[dict(side='front',kind='door',x=.1,z=0,width=1,height=2)]),
               dict(openings=[dict(side='front',kind='window',x=1,z=1,width=1,height=1,rows=0)]),
               dict(openings=[dict(side='front',kind='window',x=1,z=1,width=1,height=1,design='panelled')])]
        for case in cases:
            b=_Geometry()
            params=dict(width=10,depth=8)
            params.update(case)
            with self.subTest(case=case),self.assertRaises(ValueError):
                create_building_shell(b,**params)
            self.assertEqual(b.faces,[])


if __name__=='__main__':
    unittest.main()
