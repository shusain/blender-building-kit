"""Reusable rooftop source details and measured flat/gable mounting supports.

Ordinary-Python geometry/planning has no scene/file writes. The explicit Blender
prefab adapter reuses the shared five-role material/recipe lifecycle. Callers own
source saves, previews and checked exports. Closed hatches do not cut roof holes;
equipment is static source detail, not traversal, smoke, HVAC or Chaos gameplay.
"""
from dataclasses import dataclass, asdict
import math
import re

from .CityBuildingEntrances import Facade, _box
from .CityBuildingShell import _Geometry, _terrace_cells, _number


def _rectangle(value):
    if not isinstance(value,(list,tuple)) or len(value)!=4:
        raise ValueError('Roof rectangles need x0/y0/x1/y1')
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in value):
        raise ValueError('Roof coordinates must be finite numbers')
    if value[0]>=value[2] or value[1]>=value[3]:
        raise ValueError('Roof rectangles must have positive area')
    return tuple(value)


def _overlap(a,b):
    return min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1])


@dataclass(frozen=True)
class RoofSupport:
    """Explicit roof TOP in assembly-local meters, usable with existing sources.

    bounds is the full roof rectangle including overhang; wall_bounds is the
    gable's exterior wall rectangle. eave_z is roof TOP at the wall edge, not at
    the overhang edge. ridge_axis flat/x/y and pitch_degrees describe the same
    piecewise-linear gable profile as CityBuildingShell. exclusions reserve child
    towers/other protected rectangles. This metadata does not measure a mesh.
    """
    bounds: tuple
    eave_z: float
    ridge_axis: str = 'flat'
    pitch_degrees: float = 0.
    wall_bounds: tuple = None
    exclusions: tuple = ()

    def __post_init__(self):
        object.__setattr__(self,'bounds',_rectangle(self.bounds))
        object.__setattr__(self,'wall_bounds',_rectangle(self.wall_bounds or self.bounds))
        object.__setattr__(self,'exclusions',tuple(_rectangle(r) for r in self.exclusions))
        if isinstance(self.eave_z,bool) or not isinstance(self.eave_z,(int,float)) or not math.isfinite(self.eave_z):
            raise ValueError('Roof elevation must be finite')
        _number(self.pitch_degrees,'roof pitch',zero=True)
        if self.ridge_axis not in ('flat','x','y') or not 0<=self.pitch_degrees<75:
            raise ValueError('Support needs flat/x/y ridge and pitch below 75 degrees')
        if (self.ridge_axis=='flat') != (self.pitch_degrees==0):
            raise ValueError('Flat support needs zero pitch; gable needs positive pitch')
        b,w=self.bounds,self.wall_bounds
        if not (b[0]<=w[0]<w[2]<=b[2] and b[1]<=w[1]<w[3]<=b[3]):
            raise ValueError('Roof bounds must contain wall bounds')

    def height(self,x,y):
        """Evaluate the authored roof top, including slope beyond wall edges."""
        if self.ridge_axis=='flat':
            return self.eave_z
        i=0 if self.ridge_axis=='y' else 1
        coordinate=(x,y)[i]
        return self.eave_z+math.tan(math.radians(self.pitch_degrees))*min(coordinate-self.wall_bounds[i],self.wall_bounds[i+2]-coordinate)

    def breaks(self):
        """Grid splits needed so flashing never bridges across a gable ridge."""
        w=self.wall_bounds
        return ([(w[0]+w[2])/2],[]) if self.ridge_axis=='y' else ([],[(w[1]+w[3])/2]) if self.ridge_axis=='x' else ([],[])


def roof_support_from_section(shell_plan,section='base'):
    """Derive exact cap top and child reservations from a rectangular shell plan."""
    matches=[s for s in shell_plan['sections'] if s['id']==section]
    if len(matches)!=1:
        raise ValueError('Unknown shell roof section: '+str(section))
    s=matches[0];p=s['parameters']
    return RoofSupport(s['roof_bounds_m'],s['wall_top_m']+p['roof_thickness'],
                       p['ridge_axis'] if p['roof']=='gable' else 'flat',
                       p['roof_pitch'] if p['roof']=='gable' else 0.,s['footprint_m'],
                       tuple(c['roof_bounds_m'] for c in shell_plan['sections'] if c['parameters']['parent']==section))


DEFAULTS={'chimney':(1.,.8,1.6),'hvac':(2.6,1.6,1.),'hatch':(1.1,.9,.12),'vent':(.7,.7,.8)}


def plan_rooftop_element(element_kind,roof_support,center,*,width=None,depth=None,height=None,
                         clearance=.25,flashing=.15,curb_height=.18):
    """Validate one upright static detail and its complete horizontal reservation.

    Width/depth describe the outer curb/body, height the body above the curb;
    caps/fans/handles add their declared geometry above it. Flashing projects
    outward. clearance reserves space beyond flashing for edges/other objects;
    it is not a certified maintenance/structural clearance. HVAC/hatches require
    flat supports. Chimneys/vents can straddle a ridge with split flashing.
    """
    if element_kind not in DEFAULTS:
        raise ValueError('Rooftop kind must be chimney/hvac/hatch/vent')
    support=RoofSupport(**roof_support) if isinstance(roof_support,dict) else roof_support
    if not isinstance(support,RoofSupport):
        raise ValueError('Expected explicit RoofSupport metadata')
    if element_kind in ('hvac','hatch') and support.ridge_axis!='flat':
        raise ValueError('HVAC and hatch require a flat roof in this source kit')
    values=[a if a is not None else b for a,b in zip((width,depth,height),DEFAULTS[element_kind])]
    width,depth,height=values
    for value,label in zip(values,('width','depth','height')):
        _number(value,label)
    for value,label in ((flashing,'flashing'),(curb_height,'curb height'),(clearance,'clearance')):
        _number(value,label,zero=label=='clearance')
    if min(width,depth)<.4 or height<.08:
        raise ValueError('Rooftop body needs width/depth >= .4m and height >= .08m')
    if flashing<.08 or (element_kind=='hvac' and height<.3):
        raise ValueError('Flashing must extend >= .08m; HVAC cabinet needs height >= .3m')
    if not isinstance(center,(list,tuple)) or len(center)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in center):
        raise ValueError('Center needs two finite assembly-local coordinates')
    x,y=center
    body=[x-width/2,y-depth/2,x+width/2,y+depth/2]
    flash=[body[0]-flashing,body[1]-flashing,body[2]+flashing,body[3]+flashing]
    reserved=[flash[0]-clearance,flash[1]-clearance,flash[2]+clearance,flash[3]+clearance]
    bounds=support.bounds
    if not (bounds[0]<=reserved[0] and bounds[1]<=reserved[1] and reserved[2]<=bounds[2] and reserved[3]<=bounds[3]):
        raise ValueError('Rooftop reservation exceeds roof edge')
    if any(_overlap(reserved,r) for r in support.exclusions):
        raise ValueError('Rooftop reservation intersects a tower/protected rectangle')
    xs,ys=support.breaks()
    cells=_terrace_cells(body,[],xs,ys)
    samples=sorted({(a,b) for x0,y0,x1,y1 in cells for a,b in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))})
    curb_top=max(support.height(a,b) for a,b in samples)+curb_height
    return dict(schema=1,parameters=dict(element_kind=element_kind,roof_support=asdict(support),center=list(center),
                width=width,depth=depth,height=height,clearance=clearance,flashing=flashing,curb_height=curb_height),
                body_rect_m=body,flashing_rect_m=flash,reserved_rect_m=reserved,curb_top_m=curb_top,
                roof_contacts_m=[[a,b,support.height(a,b)] for a,b in samples],
                limits='Static closed source detail; explicit mounting metadata; no roof cut, smoke, traversal or engineering certification')


def _surface_volume(b,rect,holes,support,bottom,top,slot):
    """Closed piecewise-planar volume; shared cell edges have no internal caps."""
    xs,ys=support.breaks();edges={};start=len(b.faces)
    for x0,y0,x1,y1 in _terrace_cells(rect,holes,xs,ys):
        ring=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
        for fn,points in ((top,ring),(bottom,ring[::-1])):
            b.face([(x,y,fn(x,y)) for x,y in points],slot,(1,1,1,1),[(x/2.4,y/2.4) for x,y in points])
        for a,c in zip(ring,ring[1:]+ring[:1]):
            key=tuple(sorted((a,c)))
            if key in edges:del edges[key]
            else:edges[key]=(a,c)
    for a,c in edges.values():
        points=[(*a,bottom(*a)),(*c,bottom(*c)),(*c,top(*c)),(*a,top(*a))]
        b.face(points,slot,(1,1,1,1),[(0,0),(math.dist(a,c),0),(math.dist(a,c),top(*c)-bottom(*c)),(0,top(*a)-bottom(*a))])
    return list(range(start,len(b.faces)))


def _box_xyz(b,rect,slot):
    x0,y0,z0,x1,y1,z1=rect
    return _box(b,Facade(),(x0,z0,x1,z1),-y0,-y1,slot)


def _ring(b,x,y,inner,outer,bottom,top,slot,segments=16):
    start=len(b.faces)
    for i in range(segments):
        a,c=i*math.tau/segments,(i+1)*math.tau/segments
        points=[(x+r*math.cos(t),y+r*math.sin(t),z) for r,z,t in
                [(outer,bottom,a),(outer,bottom,c),(outer,top,c),(outer,top,a),
                 (inner,bottom,a),(inner,bottom,c),(inner,top,c),(inner,top,a)]]
        for face in ((0,1,2,3),(7,6,5,4),(3,2,6,7),(4,5,1,0)):
            b.face([points[j] for j in face],slot,(1,1,1,1),[(0,0),(1,0),(1,1),(0,1)])
    return list(range(start,len(b.faces)))


def _element_geometry(plan):
    b=_Geometry();roles={};p=plan['parameters'];support=RoofSupport(**p['roof_support'])
    x,y=p['center'];w,d,h=p['width'],p['depth'],p['height'];z=plan['curb_top_m']
    x0,y0,x1,y1=plan['body_rect_m'];body=plan['body_rect_m']
    inner=[x0+.08,y0+.08,x1-.08,y1-.08]
    roles['flashing']=_surface_volume(b,plan['flashing_rect_m'],[body],support,support.height,lambda a,c:support.height(a,c)+.025,0)
    roles['curb']=_surface_volume(b,body,[inner],support,support.height,lambda a,c:z,1)
    kind=p['element_kind']
    if kind=='chimney':
        roles['shaft']=_surface_volume(b,body,[inner],support,lambda a,c:z,lambda a,c:z+h,2)
        coping=[x0-.06,y0-.06,x1+.06,y1+.06]
        roles['coping']=_surface_volume(b,coping,[inner],support,lambda a,c:z+h,lambda a,c:z+h+.08,0)
        roles['cap_supports']=[]
        for a,c in ((x0,y0),(x1-.07,y0),(x0,y1-.07),(x1-.07,y1-.07)):
            roles['cap_supports']+=_box_xyz(b,(a,c,z+h+.08,a+.07,c+.07,z+h+.28),4)
        roles['cap']=_box_xyz(b,(x0-.08,y0-.08,z+h+.28,x1+.08,y1+.08,z+h+.36),1)
    elif kind=='hvac':
        roles['cabinet']=_box_xyz(b,(x0,y0,z,x1,y1,z+h),2)
        roles['intake_backing']=_box_xyz(b,(x0+.08,y0-.012,z+.1,x1-.08,y0-.006,z+h-.04),4)
        roles['louvers']=[]
        for i in range(6):
            level=z+.12+(h-.2)*i/6
            roles['louvers']+=_box_xyz(b,(x0+.08,y0-.035,level,x1-.08,y0-.012,level+.018),0)
        roles['fans']=[]
        radius=min(w*.17,d*.32)
        for a in (x-w/4,x+w/4):
            roles['fans']+=_ring(b,a,y,radius*.78,radius,z+h,z+h+.06,0)
            roles['fans']+=_ring(b,a,y,.015,radius*.78,z+h+.002,z+h+.01,4)
            for angle in (0,math.pi/2,math.pi,math.pi*1.5):
                points=[(a+u*math.cos(angle)-v*math.sin(angle),y+u*math.sin(angle)+v*math.cos(angle),z+h+.025)
                        for u,v in ((.03,-radius*.10),(radius*.68,-radius*.16),(radius*.68,radius*.08),(.03,radius*.10))]
                b.face(points,1,(1,1,1,1),[(0,0),(1,0),(1,1),(0,1)])
                roles['fans'].append(len(b.faces)-1)
    elif kind=='hatch':
        roles['lid']=_box_xyz(b,(x0-.025,y0-.025,z,x1+.025,y1+.025,z+h),2)
        roles['hinges']=[]
        for a in (x-w*.28,x+w*.28):
            roles['hinges']+=_box_xyz(b,(a-.06,y1-.04,z+h-.015,a+.06,y1+.045,z+h+.025),4)
        roles['handle']=[]
        for a in (x-.12,x+.09):
            roles['handle']+=_box_xyz(b,(a,y0+.12,z+h,a+.03,y0+.15,z+h+.07),4)
        roles['handle']+=_box_xyz(b,(x-.12,y0+.12,z+h+.07,x+.12,y0+.15,z+h+.1),4)
    else:
        radius=min(w,d)*.28
        roles['duct']=_ring(b,x,y,radius*.83,radius,z,z+h,0)
        roles['cap_supports']=[]
        for a in (x-radius*.6,x+radius*.6):
            roles['cap_supports']+=_box_xyz(b,(a-.025,y-.025,z+h,a+.025,y+.025,z+h+.12),4)
        roles['cap']=_ring(b,x,y,.015,min(w,d)*.46,z+h+.12,z+h+.18,1)
    return b,roles


def create_rooftop_element(b,element_kind,roof_support,center,**parameters):
    """Append validated static geometry atomically; return absolute face roles."""
    plan=plan_rooftop_element(element_kind,roof_support,center,**parameters)
    geometry,roles=_element_geometry(plan);offset=len(b.faces)
    for i,points in enumerate(geometry.faces):
        b.face(points,geometry.slots[i],geometry.colors[i],geometry.uvs[i])
    plan['roles']={key:[i+offset for i in indices] for key,indices in roles.items()}
    plan['bounds_m']=[[min(p[i] for face in geometry.faces for p in face) for i in range(3)],
                      [max(p[i] for face in geometry.faces for p in face) for i in range(3)]]
    return plan


def plan_rooftop_placements(shell_plan,elements):
    """Validate explicit shell placements; centers are section-local plan meters."""
    if not isinstance(elements,(list,tuple)):
        raise ValueError('Rooftop elements must be a portable list')
    result=[];ids=set()
    for i,item in enumerate(elements):
        allowed={'id','section','kind','center','width','depth','height','clearance','flashing','curb_height'}
        if not isinstance(item,dict) or set(item)-allowed or not {'kind','center'}<=set(item):
            raise ValueError('Rooftop placement needs kind/center and documented fields only')
        label=item.get('id','Element_'+str(i))
        if not isinstance(label,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',label) or label in ids:
            raise ValueError('Rooftop ids must be unique portable identifiers')
        ids.add(label);section=item.get('section','base')
        support=roof_support_from_section(shell_plan,section)
        origin=next(s['origin_m'] for s in shell_plan['sections'] if s['id']==section)
        center=item['center']
        if not isinstance(center,(list,tuple)) or len(center)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in center):
            raise ValueError('Placement center needs two finite coordinates')
        params={k:v for k,v in item.items() if k not in ('id','section','kind','center')}
        plan=plan_rooftop_element(item['kind'],support,[origin[0]+center[0],origin[1]+center[1]],**params)
        if any(_overlap(plan['reserved_rect_m'],r['plan']['reserved_rect_m']) for r in result):
            raise ValueError('Rooftop element reservations overlap')
        result.append(dict(id=label,section=section,plan=plan))
    return result


def create_rooftop_element_prefab(name,element_kind,roof_support,center,materials,**parameters):
    """Create a fresh Blender5 static prefab using shared material/recipe APIs.

    Roles: frame=flashing/metal edges, leaf=curb/caps, panel=shaft/cabinet/lid,
    hardware=dark intake/duct/handles; glass is unused. All parts are static;
    semantic face groups are retained in recipe.hardware.roles. Does not save,
    cut a host roof, modify existing sources or simulate access/equipment.
    """
    from .CityBuildingOpeningPrefabs import _finish
    plan=plan_rooftop_element(element_kind,roof_support,center,**parameters)
    geometry,roles=_element_geometry(plan)
    prefab=_finish(name,geometry,list(range(len(geometry.faces))),[],materials,
                   dict(kind='rooftop_element',**plan['parameters']),dict(plan=plan,roles=roles))
    prefab.root['CityRooftopElement']=element_kind
    return prefab
