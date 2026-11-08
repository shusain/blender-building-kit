"""Offline roof-contact, source-bounds and explicit placement contracts.

Runs in ordinary Python without Blender or file/scene writes. Exercises actual
piecewise roof surfaces/geometry and atomic failure, not render snapshots.
"""
from collections import Counter
import json
import math
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from blender_building_kit.CityBuildingShell import plan_building_shell,create_building_shell,_Geometry
from blender_building_kit.CityBuildingRooftops import (
    RoofSupport,roof_support_from_section,plan_rooftop_element,create_rooftop_element,plan_rooftop_placements,
)


def cross(a,b):
    return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])


def volume(faces):
    return sum(sum(a*b for a,b in zip(f[0],cross(f[i],f[i+1])))/6 for f in faces for i in range(1,len(f)-1))


class Rooftops(unittest.TestCase):
    def test_support_matches_actual_shell_top_both_gable_axes_and_overhang(self):
        for axis in ('x','y'):
            plan=plan_building_shell(12,10,floors=2,ridge_axis=axis,roof_pitch=35)
            s=roof_support_from_section(plan)
            self.assertAlmostEqual(s.height(0,0),6.16)
            self.assertAlmostEqual(s.height(6,5),plan['sections'][0]['roof_top_m'])
            self.assertAlmostEqual(s.height(-.3,-.3),6.16-.3*math.tan(math.radians(35)))
        plan=plan_building_shell(20,16,roof='flat',towers=[dict(id='Tower',offset=[3,4],width=6,depth=5,roof='flat')])
        roof=roof_support_from_section(plan,'Tower')
        self.assertAlmostEqual(roof.height(5,6),6.32)
        self.assertEqual(roof_support_from_section(plan).exclusions,((2.7,3.7,9.3,9.3),))

    def test_split_flashing_contacts_and_positive_closed_volume_across_ridge(self):
        for axis in ('x','y'):
            support=roof_support_from_section(plan_building_shell(12,10,ridge_axis=axis))
            for kind in ('chimney','vent'):
                b=_Geometry();r=create_rooftop_element(b,kind,support,[6,5])
                faces=[b.faces[i] for i in r['roles']['flashing']]
                outer=r['flashing_rect_m'];inner=r['body_rect_m']
                area=(outer[2]-outer[0])*(outer[3]-outer[1])-(inner[2]-inner[0])*(inner[3]-inner[1])
                self.assertAlmostEqual(volume(faces),area*.025,places=7)
                edges=Counter(tuple(sorted((a,c))) for f in faces for a,c in zip(f,f[1:]+f[:1]))
                self.assertTrue(all(n==2 for n in edges.values()))
                contacts=[p for f in faces for p in f if abs(p[2]-support.height(*p[:2]))<1e-8]
                self.assertTrue(contacts)
                self.assertTrue(any(abs(p[0]-6)<1e-8 for p in contacts) if axis=='y' else any(abs(p[1]-5)<1e-8 for p in contacts))
                self.assertAlmostEqual(r['curb_top_m'],support.height(6,5)+.18)

    def test_four_kinds_have_finite_nonzero_faces_uvs_roles_and_reserved_bounds(self):
        support=RoofSupport((0,0,20,20),7.)
        shapes=[]
        for kind in ('chimney','hvac','hatch','vent'):
            b=_Geometry();b.face([(0,0,0),(1,0,0),(0,1,0)],4,(1,1,1,1),[(0,0)]*3)
            r=create_rooftop_element(b,kind,support,[10,10])
            ids=[i for values in r['roles'].values() for i in values]
            self.assertEqual(sorted(ids),list(range(1,len(b.faces))))
            bounds=r['reserved_rect_m']
            for face,uv in zip(b.faces[1:],b.uvs[1:]):
                self.assertEqual(len(face),len(uv))
                self.assertTrue(all(math.isfinite(v) for p in face for v in p))
                a=[face[1][i]-face[0][i] for i in range(3)];c=[face[2][i]-face[0][i] for i in range(3)]
                self.assertGreater(sum(v*v for v in cross(a,c)),1e-16)
                self.assertTrue(all(bounds[0]<=x<=bounds[2] and bounds[1]<=y<=bounds[3] and z>=7 for x,y,z in face))
            self.assertGreater(r['bounds_m'][1][2],r['curb_top_m'])
            shapes.append(len(b.faces))
        self.assertEqual(len(set(shapes)),4)

    def test_shell_placements_roundtrip_and_static_face_ownership(self):
        params=dict(width=20,depth=16,roof='flat',towers=[dict(id='Tower',offset=[12,9],width=5,depth=4,roof='flat')],
                    rooftop_elements=[dict(id='Air',kind='hvac',center=[4,4]),dict(id='Access',kind='hatch',center=[9,4]),
                                      dict(id='Flue',kind='vent',section='Tower',center=[2.5,2])])
        plan=plan_building_shell(**params)
        decoded=json.loads(json.dumps(plan))
        self.assertEqual(json.loads(json.dumps(plan_building_shell(**decoded['parameters']))),decoded)
        self.assertEqual(plan['rooftop_elements'][2]['plan']['parameters']['center'],[14.5,11])
        b=_Geometry();report=create_building_shell(b,**params)
        self.assertEqual(sorted(i for g in report['components'] for i in g['faces']),list(range(len(b.faces))))
        self.assertEqual(sum(g['id'].startswith('Rooftop_') for g in report['components']),3)
        self.assertFalse(report['openings']) # No automatic rooftop doors/access openings.

    def test_bad_mounts_and_collisions_reject_before_caller_mutation(self):
        flat=RoofSupport((0,0,20,20),5.,exclusions=((8,8,12,12),))
        cases=[('unknown',flat,[4,4],{}),('hvac',flat,[.2,4],{}),('vent',flat,[10,10],{}),
               ('chimney',flat,[4,4],dict(width=-1)),('vent',flat,[4,4],dict(flashing=.01)),
               ('hvac',flat,[4,4],dict(height=.1)),('hatch',flat,[float('nan'),4],{})]
        pitched=roof_support_from_section(plan_building_shell(12,10))
        cases.extend((kind,pitched,[3,3],{}) for kind in ('hvac','hatch'))
        for kind,support,center,options in cases:
            b=_Geometry()
            with self.subTest(kind=kind,center=center),self.assertRaises(ValueError):
                create_rooftop_element(b,kind,support,center,**options)
            self.assertFalse(b.faces)
        for elements in ([dict(kind='vent',center=[4,4]),dict(kind='hatch',center=[4.5,4])],
                         [dict(kind='vent',section='unknown',center=[4,4])],
                         [dict(kind='vent',center=[4,4],id='same'),dict(kind='vent',center=[10,10],id='same')]):
            b=_Geometry()
            with self.assertRaises(ValueError):create_building_shell(b,20,20,roof='flat',rooftop_elements=elements)
            self.assertFalse(b.faces)


if __name__=='__main__':
    unittest.main()
