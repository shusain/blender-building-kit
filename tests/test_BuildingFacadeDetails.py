"""Offline facade kit geometry/placement contracts; ordinary Python, no writes.

Checks real clipped geometry, complete face ownership, portable input plans,
upright rotated frames and rejection before caller mutation. Blender save/reload
and protected-source comparisons remain separate opt-in source evidence.
"""
import json
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from blender_building_kit.CityBuildingEntrances import Facade
from blender_building_kit.CityBuildingFacadeDetails import plan_facade_details, create_facade_details, facade_top_from_shell
from blender_building_kit.CityBuildingShell import _Geometry, plan_building_shell


class FacadeDetails(unittest.TestCase):
    def test_seams_end_exactly_on_gable_profile_and_projected_eaves(self):
        shell=plan_building_shell(12,9,floor_height=4.2,roof_pitch=22)
        outline=facade_top_from_shell(shell,'front',projection=.022)
        self.assertAlmostEqual(outline['height'],4.2+6*math.tan(math.radians(22)))
        plan=plan_facade_details(**outline,elements=[dict(id='Panels',kind='panel_seams',spacing=.9,height=None)])
        for poly in plan['placements'][0]['profiles_m']:
            # Both outer top corners lie on the actual sloped underside.
            a,b=min(p[0] for p in poly),max(p[0] for p in poly)
            for x in (a,b):
                top=max(p[1] for p in poly if abs(p[0]-x)<1e-8)
                self.assertAlmostEqual(top,4.2+min(x,12-x)*math.tan(math.radians(22)))
        side=facade_top_from_shell(shell,'right',projection=.022)
        self.assertAlmostEqual(side['height'],4.2-.022*math.tan(math.radians(22)))
        with self.assertRaisesRegex(ValueError,'bounds'):
            plan_facade_details(**outline,elements=[dict(id='Box',kind='service_box',x=.6,z=5)])
        for profile in ([[0,4],[8,3],[7,4]],[[1,4],[8,4]],[[0,5],[8,4]]):
            with self.assertRaises(ValueError):plan_facade_details(8,4,[dict(id='P',kind='panel_seams')],top_profile=profile)

    def test_seams_clip_around_actual_apertures_and_service_reservations(self):
        hole=dict(x=2,z=0,width=1.2,height=2.35)
        rows=[dict(id='Ribs',kind='panel_seams',spacing=1,height=3.65),
              dict(id='Cabinet',kind='service_box',x=5,z=.5)]
        g=_Geometry();r=create_facade_details(g,8,4.2,rows,openings=[hole])
        seam=next(p for p in r['plan']['placements'] if p['kind']=='panel_seams')
        cabinet=next(p for p in r['plan']['placements'] if p['kind']=='service_box')['bounds_m']
        reservations=[[1.88,-.12,3.32,2.47],[cabinet[0]-.12,cabinet[1]-.12,cabinet[2]+.12,cabinet[3]+.12]]
        self.assertTrue(seam['strips_m'])
        for rect in seam['strips_m']:
            for blocked in reservations:
                self.assertFalse(rect[0]<blocked[2] and blocked[0]<rect[2] and rect[1]<blocked[3] and blocked[1]<rect[3])
        # At x=3 the rib actually begins above the door, not behind the insert.
        cut=[r for r in seam['strips_m'] if r[0]<3<r[2]]
        self.assertEqual(len(cut),1)
        self.assertAlmostEqual(cut[0][1],2.47)
        self.assertTrue(all(math.isfinite(v) for f in g.faces for p in f for v in p))
        self.assertTrue(all(len(uv)==len(face) for uv,face in zip(g.uvs,g.faces)))

    def test_explicit_exclusions_clip_and_reject_solid_details(self):
        exclusion=dict(x=1,z=1,width=2,height=.5)
        r=plan_facade_details(8,4,[dict(id='Ribs',kind='panel_seams',spacing=2,height=3.5)],exclusions=[exclusion])
        strips=r['placements'][0]['strips_m'];at_two=[p for p in strips if p[0]<2<p[2]]
        self.assertEqual(len(at_two),2)
        self.assertAlmostEqual(at_two[0][3],.88)
        self.assertAlmostEqual(at_two[1][1],1.62)
        with self.assertRaisesRegex(ValueError,'intersects'):
            plan_facade_details(8,4,[dict(id='Box',kind='service_box',x=2)],exclusions=[exclusion])

    def test_all_families_have_complete_face_roles_and_grounded_bollard(self):
        rows=[dict(id='Pipe',kind='downpipe',x=.5),dict(id='Box',kind='service_box',x=2),
              dict(id='Vent',kind='wall_vent',x=4),dict(id='Guard',kind='bollard',x=6)]
        g=_Geometry();r=create_facade_details(g,8,4,rows)
        faces=[i for group in r['elements'] for ids in group['roles'].values() for i in ids]
        self.assertEqual(sorted(faces),list(range(len(g.faces))))
        guard=r['elements'][-1]
        points=[p for ids in guard['roles'].values() for i in ids for p in g.faces[i]]
        self.assertEqual(min(p[2] for p in points),0)
        self.assertLess(max(p[1] for p in points),0) # ground guard sits outward
        self.assertEqual(set(g.slots),{0,1,2,4})

    def test_rotated_translated_facade_and_json_roundtrip(self):
        params=dict(width=8,height=4,elements=[dict(id='Box',kind='service_box',x=2)],
                    facade=Facade((10,5,2),(0,1,0),(0,0,1)))
        plan=plan_facade_details(**params)
        portable=json.loads(json.dumps(plan['parameters']));portable['facade']=Facade(**portable['facade'])
        self.assertEqual(json.loads(json.dumps(plan_facade_details(**portable))),json.loads(json.dumps(plan)))
        g=_Geometry();r=create_facade_details(g,**params)
        points=[p for f in g.faces for p in f]
        self.assertGreater(max(p[0] for p in points),10) # right x up = +X
        self.assertAlmostEqual(min(p[2] for p in points),2.5)

    def test_bad_specs_are_atomic_and_do_not_mutate_input(self):
        cases=[dict(id='Bad',kind='unknown',x=1),dict(id='Bad',kind='downpipe',x=True),
               dict(id='Bad',kind='service_box',x=.1),dict(id='Bad',kind='bollard',x=1,z=.1),
               dict(id='Bad',kind='wall_vent',x=2,unrecognised=True),
               dict(id='Bad',kind='panel_seams',spacing=0),dict(id='Bad',kind='downpipe',x=1,height=5)]
        for item in cases:
            g=_Geometry();before=json.dumps(item)
            with self.subTest(item=item),self.assertRaises(ValueError):create_facade_details(g,8,4,[item])
            self.assertEqual(g.faces,[]);self.assertEqual(json.dumps(item),before)
        with self.assertRaisesRegex(ValueError,'intersects'):
            create_facade_details(_Geometry(),8,4,[dict(id='A',kind='service_box',x=2),dict(id='B',kind='downpipe',x=2)])
        with self.assertRaisesRegex(ValueError,'unique'):
            plan_facade_details(8,4,[dict(id='A',kind='downpipe',x=1),dict(id='A',kind='downpipe',x=7)])


if __name__=='__main__': unittest.main()
