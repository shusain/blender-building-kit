"""Offline pipe/port geometry contracts; ordinary Python, no scene/file writes.

Checks exact endpoint frames, sampled circular bends, closed hollow geometry,
coupling diameters/clocking and complete face ownership plus atomic rejection.
"""
import json
import math
from pathlib import Path
import sys
from collections import Counter
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from blender_building_kit.CityBuildingPipes import PipePort,plan_pipe_route,create_pipe_route,create_pipe_socket
from blender_building_kit.CityBuildingShell import _Geometry


def volume(faces):
    cross=lambda a,b:(a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
    return sum(sum(x*y for x,y in zip(f[0],cross(f[i],f[i+1])))/6 for f in faces for i in range(1,len(f)-1))


def closed(test,g):
    edges=Counter()
    for face in g.faces:
        pts=[tuple(round(v,8) for v in p) for p in face]
        for a,b in zip(pts,pts[1:]+pts[:1]):
            test.assertNotEqual(a,b);edges[tuple(sorted((a,b)))]+=1
    test.assertTrue(all(n==2 for n in edges.values()))
    test.assertGreater(volume(g.faces),0)
    test.assertTrue(all(len(uv)==len(face) for uv,face in zip(g.uvs,g.faces)))
    for uv in g.uvs:
        test.assertGreater(abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(uv,uv[1:]+uv[:1]))),1e-12)


class Pipes(unittest.TestCase):
    def ports(self,d=.25,style='flanged'):return PipePort((0,0,1),(1,0,0),d,coupling=style),PipePort((6,2,3),(-1,0,0),d,coupling=style)
    def route(self):return [(0,0,1),(1.5,0,1),(1.5,0,3),(4.5,0,3),(4.5,2,3),(6,2,3)]

    def test_end_clocking_can_differ_without_a_crack_or_frame_jump(self):
        a,b=self.ports();b=PipePort(b.position,b.normal,b.diameter,up=(0,1,0))
        p=plan_pipe_route(a,b,self.route())
        self.assertAlmostEqual(math.dist(p['rings'][-1]['up'],b.up),0)
        self.assertAlmostEqual(math.dist(p['rings'][0]['up'],a.up),0)
        g=_Geometry();create_pipe_route(g,a,b,self.route());closed(self,g)

    def test_bend_tangency_end_frames_and_three_physical_diameters(self):
        for d in (.1,.25,.5):
            a,b=self.ports(d);p=plan_pipe_route(a,b,self.route())
            self.assertEqual(p['rings'][0]['center'],a.position);self.assertEqual(p['rings'][-1]['center'],b.position)
            self.assertAlmostEqual(math.dist(p['rings'][0]['up'],a.up),0)
            self.assertAlmostEqual(math.dist(p['rings'][-1]['up'],b.up),0)
            self.assertEqual(len(p['bends']),4)
            self.assertTrue(all(abs(c['take_up']-d*1.5)<1e-8 for c in p['bends']))
            for s in p['rings']:
                self.assertAlmostEqual(sum(t*u for t,u in zip(s['tangent'],s['up'])),0)
                self.assertAlmostEqual(sum(u*u for u in s['up']),1)
            portable=json.loads(json.dumps(p['parameters']))
            self.assertEqual(json.loads(json.dumps(plan_pipe_route(**portable))),json.loads(json.dumps(p)))

    def test_hollow_sweep_and_socket_closed_roles_clocking(self):
        for style in ('plain','flanged'):
            a,b=self.ports(style=style)
            g=_Geometry();r=create_pipe_route(g,a,b,self.route(),style=style);closed(self,g)
            self.assertEqual(sorted(i for ids in r['roles'].values() for i in ids),list(range(len(g.faces))))
            for port in (a,b):
                socket=_Geometry();sr=create_pipe_socket(socket,port,style=style);closed(self,socket)
                self.assertEqual(sr['parameters']['port']['up'],port.up)
                # The matching annulus sits exactly at the specified plane.
                faces=[socket.faces[i] for i in sr['roles']['ends']]
                mating=[f for f in faces if all(abs(sum((x-y)*n for x,y,n in zip(v,port.position,port.normal)))<1e-8 for v in f)]
                self.assertEqual(len(mating),16)

    def test_plain_straight_volume_matches_polygonal_hollow_tube(self):
        a=PipePort((0,0,0),(1,0,0),.4,coupling='plain');b=PipePort((3,0,0),(-1,0,0),.4,coupling='plain')
        g=_Geometry();create_pipe_route(g,a,b,[a.position,b.position],style='plain',segments=16)
        expected=8*math.sin(math.pi/8)*(.2**2-(.2-.032)**2)*3
        self.assertAlmostEqual(volume(g.faces),expected,places=8);closed(self,g)

    def test_bad_connections_and_impossible_bends_reject_before_writes(self):
        a,b=self.ports();cases=[dict(port_b=PipePort(b.position,b.normal,.5)),dict(port_b=PipePort(b.position,b.normal,.25,coupling='plain')),dict(points=[a.position,b.position]),
            dict(bend_radius=.1),dict(style='unknown'),dict(segments=7),dict(wall_thickness=.2),
            dict(points=[a.position,(.1,0,1),(.1,0,3),(4.5,0,3),(4.5,2,3),b.position])]
        for case in cases:
            p=dict(port_a=a,port_b=b,points=self.route());p.update(case);g=_Geometry()
            with self.subTest(case=case),self.assertRaises(ValueError):create_pipe_route(g,**p)
            self.assertEqual(g.faces,[])
        with self.assertRaises(ValueError):PipePort((0,0,0),(0,0,1),.2)
        with self.assertRaises(ValueError):PipePort((0,0,0),(1,0,0),True)


if __name__=='__main__':unittest.main()
