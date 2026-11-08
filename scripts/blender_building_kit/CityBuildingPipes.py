"""Connected pipe source studies: measured ports, filleted routes and couplings.

Ordinary-Python planning/geometry, lazy Blender prefabs through the existing
five-role lifecycle. Caller supplies explicit routes and machine port datums;
no network, obstacle routing, host mesh cuts, simulation or files on import.
All diameters are physical outer meters, not nominal/DN or rated hardware.
"""
from dataclasses import dataclass, asdict
import math

from .CityBuildingEntrances import Facade
from .CityBuildingShell import _Geometry

PIPE_STYLES=('plain','flanged')


def _number(v,label):
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0:
        raise ValueError(label+' must be finite and positive')


def pipe_connection_spec(diameter):
    """Canonical project visual end-piece dimensions from physical pipe OD."""
    _number(diameter,'diameter')
    return dict(diameter=diameter,flange_radius=.9*diameter,flange_length=.18*diameter,
                socket_back=.6*diameter,bolt_circle_radius=.7*diameter,
                bolt_radius=.055*diameter,bolt_half_length=.03*diameter,
                bolt_center=.215*diameter,bolt_count=8,collar_radius=.7*diameter,collar_neck=.2*diameter)


def _vector(v):
    if not isinstance(v,(list,tuple)) or len(v)!=3 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in v):
        raise ValueError('Expected finite three-component vector')
    return tuple(v)


def _add(a,b):return tuple(x+y for x,y in zip(a,b))
def _sub(a,b):return tuple(x-y for x,y in zip(a,b))
def _mul(a,s):return tuple(x*s for x in a)
def _dot(a,b):return sum(x*y for x,y in zip(a,b))
def _cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def _unit(a):
    n=math.sqrt(_dot(a,a))
    if n<1e-10:raise ValueError('Zero-length direction')
    return _mul(a,1/n)
def _rotate(v,n,a):return _add(_add(_mul(v,math.cos(a)),_mul(_cross(n,v),math.sin(a))),_mul(n,_dot(n,v)*(1-math.cos(a))))


@dataclass(frozen=True)
class PipePort:
    """Project visual coupling datum in a common parent frame, meters.

    position is the mating face center; normal points OUT of the machine into
    the pipe. up is a perpendicular unit clocking vector for rings/bolt patterns.
    diameter is the physical pipe OD at the joint. Bake scale before connecting.
    coupling is plain/flanged; both ends must agree and geometry derives from
    pipe_connection_spec. These are project visual proportions.
    """
    position: tuple
    normal: tuple
    diameter: float
    up: tuple=(0,0,1)
    coupling: str='flanged'

    def __post_init__(self):
        for key in ('position','normal','up'):object.__setattr__(self,key,_vector(getattr(self,key)))
        _number(self.diameter,'diameter')
        if self.coupling not in PIPE_STYLES:raise ValueError('Port coupling must be plain/flanged')
        if abs(_dot(self.normal,self.normal)-1)>1e-7 or abs(_dot(self.up,self.up)-1)>1e-7 or abs(_dot(self.normal,self.up))>1e-7:
            raise ValueError('Port normal/up must be perpendicular unit vectors')


def _port(p):
    if isinstance(p,dict):return PipePort(**p)
    if isinstance(p,PipePort):return p
    raise ValueError('Expected PipePort')


def _settings(port,style,wall_thickness,segments):
    p=_port(port)
    style=p.coupling if style is None else style
    if style not in PIPE_STYLES:raise ValueError('Pipe style must be plain/flanged')
    if style!=p.coupling:raise ValueError('Requested style differs from port coupling')
    wall=p.diameter*.08 if wall_thickness is None else wall_thickness
    _number(wall,'wall thickness')
    if wall>=p.diameter/2:raise ValueError('Wall consumes pipe bore')
    if type(segments) is not int or segments<8 or segments%4:raise ValueError('Ring segments must be a multiple of four, >=8')
    return p,wall


def plan_pipe_route(port_a,port_b,points,*,bend_radius=None,wall_thickness=None,style=None,segments=16):
    """Validate and sample one explicit A->B route, without caller mutation.

    Endpoint leads follow +A.normal and -B.normal. Interior waypoints are sharp
    design corners replaced by tangent circular fillets, default radius=1.5 OD.
    Radius must be >=OD; each straight must fit its two fillet take-ups and end
    flange length. Remove collinear/reversing/repeated waypoints. No reducers,
    branches or automatic obstacle/self-intersection detection in this slice.
    Project proportions: flange OD=1.8 OD, thickness=.18 OD, eight bolt heads on
    diameter1.4 OD; socket back datum=.6 OD behind the mating face. Appearance is
    caller material-bound. Socket and route use identical mating/clocking rules.
    """
    a,wall=_settings(port_a,style,wall_thickness,segments);b=_port(port_b);d=a.diameter;style=a.coupling;spec=pipe_connection_spec(d)
    if abs(d-b.diameter)>1e-8:raise ValueError('Port diameters differ; reducers are not supported')
    if a.coupling!=b.coupling:raise ValueError('Port coupling styles differ')
    if not isinstance(points,(list,tuple)) or len(points)<2:raise ValueError('Route needs at least two points')
    pts=[_vector(p) for p in points]
    if math.dist(pts[0],a.position)>1e-7 or math.dist(pts[-1],b.position)>1e-7:raise ValueError('Route endpoints must equal port mating centers')
    lengths=[math.dist(p,q) for p,q in zip(pts,pts[1:])]
    if any(v<1e-7 for v in lengths):raise ValueError('Repeated/degenerate route points')
    directions=[_unit(_sub(q,p)) for p,q in zip(pts,pts[1:])]
    if _dot(directions[0],a.normal)<1-1e-7 or _dot(directions[-1],b.normal)>-1+1e-7:raise ValueError('Endpoint lead must match port outward direction')
    radius=d*1.5 if bend_radius is None else bend_radius;_number(radius,'bend radius')
    if radius<d:raise ValueError('Bend radius must be >= pipe OD')
    take=[0.]*len(pts);corners={}
    for i in range(1,len(pts)-1):
        u,v=directions[i-1],directions[i];dot=_dot(u,v)
        if abs(dot)>1-1e-8:raise ValueError('Remove collinear or reversing waypoints')
        angle=math.acos(max(-1,min(1,dot)));n=_unit(_cross(u,v));take[i]=radius*math.tan(angle/2)
        entry=_sub(pts[i],_mul(u,take[i]));center=_add(entry,_mul(_cross(n,u),radius))
        corners[i]=dict(entry=entry,center=center,normal=n,angle=angle)
    flange=spec['flange_length'] if style=='flanged' else 0
    for i,length in enumerate(lengths):
        reserve=take[i]+take[i+1]+(flange if i==0 else 0)+(flange if i==len(lengths)-1 else 0)
        if length<=reserve+1e-6:raise ValueError('Route straight too short for bends/coupling')
    samples=[dict(center=pts[0],tangent=directions[0])]
    for i in range(1,len(pts)-1):
        c=corners[i];samples.append(dict(center=c['entry'],tangent=directions[i-1]))
        radial=_sub(c['entry'],c['center']);steps=max(2,math.ceil(c['angle']/(math.pi/24)))
        for j in range(1,steps+1):
            v=_rotate(radial,c['normal'],c['angle']*j/steps)
            samples.append(dict(center=_add(c['center'],v),tangent=_unit(_cross(c['normal'],v))))
    samples.append(dict(center=pts[-1],tangent=directions[-1]))
    if flange:
        samples.insert(1,dict(center=_add(a.position,_mul(a.normal,flange)),tangent=directions[0]))
        samples.insert(-1,dict(center=_add(b.position,_mul(b.normal,flange)),tangent=directions[-1]))
    distance=0.;up=a.up;previous=samples[0]['tangent']
    for i,s in enumerate(samples):
        t=s['tangent'];axis=_cross(previous,t)
        if _dot(axis,axis)>1e-16:up=_rotate(up,_unit(axis),math.acos(max(-1,min(1,_dot(previous,t)))))
        up=_unit(_sub(up,_mul(t,_dot(up,t))))
        if i:distance+=math.dist(s['center'],samples[i-1]['center'])
        s.update(up=up,length=distance);previous=t
    delta=math.atan2(_dot(_cross(up,b.up),previous),_dot(up,b.up))
    for s in samples:s['up']=_rotate(s['up'],s['tangent'],delta*s['length']/distance)
    rings=[]
    for i,s in enumerate(samples):
        r=d/2
        if flange and i in (0,1,len(samples)-2,len(samples)-1):r=spec['flange_radius']
        if flange and i==len(samples)-2:rings.append(dict(s,radius=d/2))
        rings.append(dict(s,radius=r))
        if flange and i==1:rings.append(dict(s,radius=d/2))
    return dict(schema=1,parameters=dict(port_a=asdict(a),port_b=asdict(b),points=[list(p) for p in pts],bend_radius=radius,
                wall_thickness=wall,style=style,segments=segments),rings=rings,length_m=distance,
                bends=[dict(index=i,radius=radius,take_up=take[i],angle_degrees=math.degrees(c['angle'])) for i,c in corners.items()],
                limits='Explicit visual route; no obstacle/self-intersection detection, flow, pressure, reducers or branches')


def _circle(c,t,up,r,n):
    side=_cross(t,up)
    return [_add(c,_add(_mul(up,r*math.cos(2*math.pi*j/n)),_mul(side,r*math.sin(2*math.pi*j/n)))) for j in range(n)]


def _tube(g,rings,inner,n):
    roles=dict(body=[],bore=[],ends=[],couplings=[])
    body_radius=min(s['radius'] for s in rings)
    outer=[_circle(s['center'],s['tangent'],s['up'],s['radius'],n) for s in rings]
    def face(key,points,slot,uv):roles[key].append(len(g.faces));g.face(points,slot,(1,1,1,1),uv)
    def radial_uv(r,j):return (r*math.cos(2*math.pi*j/n),r*math.sin(2*math.pi*j/n))
    for i,(a,b) in enumerate(zip(rings,rings[1:])):
        shoulder=math.dist(a['center'],b['center'])<1e-8
        flange=shoulder or a['radius']>body_radius+1e-9 or b['radius']>body_radius+1e-9
        for j in range(n):
            k=(j+1)%n;points=[outer[i][j],outer[i][k],outer[i+1][k],outer[i+1][j]]
            uv=[radial_uv(a['radius'],j),radial_uv(a['radius'],j+1),radial_uv(b['radius'],j+1),radial_uv(b['radius'],j)] if shoulder else [(j/n*math.tau*a['radius'],a['length']),((j+1)/n*math.tau*a['radius'],a['length']),((j+1)/n*math.tau*b['radius'],b['length']),(j/n*math.tau*b['radius'],b['length'])]
            face('couplings' if flange else 'body',points,0 if flange else 1,uv)
    unique=[s for i,s in enumerate(rings) if i==0 or math.dist(s['center'],rings[i-1]['center'])>1e-8]
    inside=[_circle(s['center'],s['tangent'],s['up'],inner,n) for s in unique]
    for i,(a,b) in enumerate(zip(unique,unique[1:])):
        for j in range(n):
            k=(j+1)%n;face('bore',[inside[i][j],inside[i+1][j],inside[i+1][k],inside[i][k]],2,[(j/n*math.tau*inner,a['length']),(j/n*math.tau*inner,b['length']),((j+1)/n*math.tau*inner,b['length']),((j+1)/n*math.tau*inner,a['length'])])
    for index,s in ((0,rings[0]),(-1,rings[-1])):
        inner_ring=_circle(s['center'],s['tangent'],s['up'],inner,n)
        for j in range(n):
            k=(j+1)%n;pts=[outer[index][j],outer[index][k],inner_ring[k],inner_ring[j]];uv=[radial_uv(s['radius'],j),radial_uv(s['radius'],j+1),radial_uv(inner,j+1),radial_uv(inner,j)]
            if index==0:pts.reverse();uv.reverse()
            face('ends',pts,0,uv)
    return roles


def _bolts(g,port,back=False):
    p=_port(port);d=p.diameter;axis=p.normal;up=p.up;side=_cross(axis,up);roles=[];spec=pipe_connection_spec(d)
    for j in range(spec['bolt_count']):
        angle=j*2*math.pi/spec['bolt_count'];radial=_add(_mul(up,math.cos(angle)),_mul(side,math.sin(angle)))
        c=_add(p.position,_add(_mul(radial,spec['bolt_circle_radius']),_mul(axis,(-1 if back else 1)*spec['bolt_center'])))
        rings=[_circle(_add(c,_mul(axis,k*spec['bolt_half_length'])),axis,up,spec['bolt_radius'],6) for k in (-1,1)]
        for k in range(6):
            q=(k+1)%6;roles.append(len(g.faces));g.face([rings[0][k],rings[0][q],rings[1][q],rings[1][k]],4,(1,1,1,1),[(0,0),(1,0),(1,1),(0,1)])
        for ring,reverse in ((rings[0],True),(rings[1],False)):
            roles.append(len(g.faces));points=list(reversed(ring)) if reverse else ring
            g.face(points,4,(1,1,1,1),[(math.cos(k*math.pi/3),math.sin(k*math.pi/3)) for k in (range(5,-1,-1) if reverse else range(6))])
    return roles


def create_pipe_route(b,port_a,port_b,points,**options):
    """Append a continuous hollow filleted sweep, buffered before caller writes.

    Slots: frame=couplings, leaf=outer pipe, panel=bore, hardware=bolt heads;
    glass unused. Mating annuli touch matching socket faces without volume
    overlap. UVs follow ring angle/length; shoulders have planar UVs.
    """
    plan=plan_pipe_route(port_a,port_b,points,**options);p=plan['parameters'];g=_Geometry()
    roles=_tube(g,plan['rings'],p['port_a']['diameter']/2-p['wall_thickness'],p['segments'])
    if p['style']=='flanged':roles['bolts']=_bolts(g,port_a)+_bolts(g,port_b)
    start=len(b.faces)
    for f,s,c,uv in zip(g.faces,g.slots,g.colors,g.uvs):b.face(f,s,c,uv)
    return dict(plan=plan,roles={k:[i+start for i in ids] for k,ids in roles.items()})


def create_pipe_socket(b,port,*,style=None,wall_thickness=None,segments=16):
    """Append matching machine-side end piece; back datum is -.6 OD * normal."""
    p,wall=_settings(port,style,wall_thickness,segments);d=p.diameter;g=_Geometry();style=p.coupling;spec=pipe_connection_spec(d)
    profile=[(-spec['socket_back'],d/2),(-spec['flange_length'],d/2),(-spec['flange_length'],spec['flange_radius']),(0,spec['flange_radius'])] if style=='flanged' else [(-spec['socket_back'],spec['collar_radius']),(-spec['collar_neck'],spec['collar_radius']),(-spec['collar_neck'],d/2),(0,d/2)]
    rings=[dict(center=_add(p.position,_mul(p.normal,x)),tangent=p.normal,up=p.up,radius=r,length=x+spec['socket_back']) for x,r in profile]
    roles=_tube(g,rings,d/2-wall,segments)
    if style=='flanged':roles['bolts']=_bolts(g,p,True)
    start=len(b.faces)
    for f,s,c,uv in zip(g.faces,g.slots,g.colors,g.uvs):b.face(f,s,c,uv)
    return dict(parameters=dict(port=asdict(p),style=style,wall_thickness=wall,segments=segments),roles={k:[i+start for i in ids] for k,ids in roles.items()})


def _anchor(port):
    p=_port(port);return Facade(p.position,p.up,_cross(p.normal,p.up))


def create_pipe_route_prefab(name,port_a,port_b,points,materials,**options):
    """Fresh editable pipe root with EndA/EndB anchors and portable pipe_route recipe."""
    import json
    from .CityBuildingOpeningPrefabs import _finish,add_assembly_helpers
    g=_Geometry();report=create_pipe_route(g,port_a,port_b,points,**options)
    pf=_finish(name,g,list(range(len(g.faces))),[],materials,dict(kind='pipe_route',**report['plan']['parameters']),report)
    add_assembly_helpers(pf,{'EndA':_anchor(port_a),'EndB':_anchor(port_b)})
    pf.root['CityPipePorts']=json.dumps(dict(a=asdict(_port(port_a)),b=asdict(_port(port_b))))
    return pf


def create_pipe_socket_prefab(name,port,materials,**options):
    """Fresh machine-side coupling root; parent to custom machinery after creation."""
    import json
    from .CityBuildingOpeningPrefabs import _finish,add_assembly_helpers
    g=_Geometry();report=create_pipe_socket(g,port,**options)
    pf=_finish(name,g,list(range(len(g.faces))),[],materials,dict(kind='pipe_socket',**report['parameters']),report)
    add_assembly_helpers(pf,{'Connection':_anchor(port)});pf.root['CityPipePort']=json.dumps(asdict(_port(port)))
    return pf


def pipe_port_from_object(root):
    """Read a socket's port into world coordinates; reject unbaked scale/reflection."""
    import json
    from mathutils import Vector
    p=PipePort(**json.loads(root['CityPipePort']));m=root.matrix_world.to_3x3()
    if abs(m.determinant()-1)>1e-6 or any(abs((m@Vector(v)).length-1)>1e-6 for v in ((1,0,0),(0,1,0),(0,0,1))):
        raise ValueError('Bake socket parent scale/reflection before reading physical port')
    return PipePort(tuple(root.matrix_world@Vector(p.position)),tuple(m@Vector(p.normal)),p.diameter,tuple(m@Vector(p.up)),p.coupling)
