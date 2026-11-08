"""Reusable planar facade/roof trim and varied canopy primitives.

Ordinary Python mesh-builder API, using the same meter Facade/face contract as
CityBuildingEntrances. Calls append geometry only; no scene/files/materials or
production buildings are changed. Building recipes choose arrangement, dimensions
and material slots. Ground-following entrances and image composition stay separate.
"""
import math
from dataclasses import dataclass, asdict
from .CityBuildingEntrances import Facade,Opening,create_wall,_positive,_slot,_box,_prism


@dataclass(frozen=True)
class TrimBand:
    """Rectangular wall band: vertical height, outward projection, inward embed.

    All distances are meters relative to the exterior wall plane. The intentional
    embed seats trim in the wall; it is not a gap or an extra placement offset.
    """
    height: float = .14
    projection: float = .08
    embed: float = .02
    slot: int = 1

    def __post_init__(self):
        _positive(self.height,'band height');_positive(self.projection,'band projection')
        _positive(self.embed,'band embed',zero=True);_slot(self.slot)


class _TrimProbe:
    """Validate complete planned operations before a caller's mesh is modified."""
    def __init__(self):self.faces=[]
    def face(self,points,slot,color,uv=None):self.faces.append(points)


def plan_building_trim(width, depth, floors, floor_height=3., *, origin=(0,0,0), yaw_degrees=0.,
                       base=TrimBand(.18,.08,.02), floor=TrimBand(.12,.06,.02),
                       roof=TrimBand(.22,.12,.02), base_offset=0., floor_offset=0.,
                       roof_offset=0., openings=None, opening_clearance=.025, roof_cap_thickness=.04):
    """Plan trim for a rectangular upright building, without scene/file writes.

    Origin is the exterior FRONT-LEFT wall corner at ground-floor level; +X is
    width, +Y is depth, +Z is up, followed by optional world yaw/translation.
    Floors end at n*floor_height. Base BOTTOM, inter-floor CENTER and roof TOP
    anchor their respective offsets. Roof refers to the flat wall/eave datum,
    not a generated pitched roof. A None profile disables that family.

    openings maps front/right/back/left to existing Opening records or JSON
    dictionaries, in each facade's left-to-right coordinates when viewed from
    outside. Touching bands are cut around openings plus clearance; corner-
    touching cuts, overlapping band elevations and out-of-body bands fail.
    Returns JSON-safe parameters, world facade frames, datums, opening zones,
    exact per-piece placements and create_trim operations. Replan from parameters
    on resize/floor updates; no previous derived offsets should be carried over.
    assembly_seats separates actual wall top from the finished eave/cap top,
    avoiding overlapping wall/trim/cap top faces. roof_cap_thickness=0 omits the
    cap seat; the caller owns any alternate roof. No roof mesh is emitted here.
    """
    for v,label in ((width,'building width'),(depth,'building depth'),(floor_height,'floor height')):_positive(v,label)
    if type(floors) is not int or floors<1:raise ValueError('Building floors must be a positive integer')
    for v,label in ((yaw_degrees,'yaw'),(base_offset,'base offset'),(floor_offset,'floor offset'),(roof_offset,'roof offset')):
        if not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError(label+' must be finite')
    _positive(opening_clearance,'opening clearance',zero=True)
    _positive(roof_cap_thickness,'roof cap thickness',zero=True)
    a=math.radians(yaw_degrees);right=(math.cos(a),math.sin(a),0);forward=(-math.sin(a),math.cos(a),0)
    plane=Facade(origin,right,forward);height=floors*floor_height
    _positive(height,'building height')
    if roof_cap_thickness>=height:raise ValueError('Roof cap consumes building height')
    profiles=[p if p is None or isinstance(p,TrimBand) else TrimBand(**p) for p in (base,floor,roof)]
    names=('front','right','back','left');spans=(width,depth,width,depth)
    starts=((0,0),(width,0),(width,depth),(0,depth));directions=((1,0),(0,1),(-1,0),(0,-1))
    facade_frames={}
    for name,(x,y),(dx,dy),span in zip(names,starts,directions,spans):
        r=tuple(dx*u+dy*v for u,v in zip(right,forward))
        facade_frames[name]=dict(frame=asdict(Facade(plane.point(x,y,0),r,(0,0,1))),width_m=span,height_m=height)
    if openings is None:openings={}
    if not isinstance(openings,dict) or set(openings)-set(names):raise ValueError('Unknown building opening facade')
    clean={}
    for name,span in zip(names,spans):
        clean[name]=[]
        for value in openings.get(name,[]):
            o=value if isinstance(value,Opening) else Opening(**value)
            if o.x<0 or o.z<0 or o.x+o.width>span or o.z+o.height>height-roof_cap_thickness:
                raise ValueError('Opening exceeds '+name+' building facade')
            clean[name].append(asdict(o))
        clean[name].sort(key=lambda o:(o['x'],o['z'],o['width'],o['height']))
    bands=[]
    def band(key,p,anchor,offset,alignment):
        if p is None:return
        if min(width,depth)<=2*p.embed:raise ValueError('Band embed consumes building footprint')
        lo=anchor+offset-(p.height if alignment=='top' else p.height/2 if alignment=='center' else 0)
        hi=lo+p.height
        if lo < -1e-9 or hi > height+1e-9:raise ValueError(key+' band exceeds wall height')
        bands.append(dict(id=key,profile=asdict(p),anchor_m=anchor,alignment=alignment,offset_m=offset,z_range_m=[lo,hi]))
    band('base',profiles[0],0,base_offset,'bottom')
    for level in range(1,floors):band('floor_'+str(level),profiles[1],level*floor_height,floor_offset,'center')
    band('roof',profiles[2],height,roof_offset,'top')
    bands.sort(key=lambda b:(b['z_range_m'][0],b['id']))
    if any(a['z_range_m'][1]>=b['z_range_m'][0]-1e-9 for a,b in zip(bands,bands[1:])):
        raise ValueError('Building bands overlap/touch vertically; reduce profile heights or offsets')
    operations=[];probe=_TrimProbe()
    for band in bands:
        p=TrimBand(**band['profile']);c=(p.projection-p.embed)/2;lo,hi=band['z_range_m']
        vertices=[(-c,-c),(width+c,-c),(width+c,depth+c),(-c,depth+c)]
        lengths=[width+2*c,depth+2*c,width+2*c,depth+2*c];knots=[0.]
        for length in lengths:knots.append(knots[-1]+length)
        cuts=[]
        for index,name in enumerate(names):
            for o in clean[name]:
                if o['z']-opening_clearance>=hi or o['z']+o['height']+opening_clearance<=lo:continue
                x0=o['x']-opening_clearance;x1=o['x']+o['width']+opening_clearance
                if x0<=p.embed+1e-6 or x1>=spans[index]-p.embed-1e-6:
                    raise ValueError(band['id']+' opening cut reaches '+name+' corner; split/design corner explicitly')
                cuts.append((knots[index]+x0+c,knots[index]+x1+c))
        merged=[]
        for start,end in sorted(cuts):
            if merged and start<=merged[-1][1]+1e-9:merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
            else:merged.append((start,end))
        def at(s):
            s=s%knots[-1]
            i=next(i for i in range(4) if s<knots[i+1])
            t=(s-knots[i])/lengths[i];a,b=vertices[i],vertices[(i+1)%4]
            return (a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1]))
        paths=[]
        if not merged:paths=[(vertices,True)]
        else:
            for i,(_,end) in enumerate(merged):
                stop=merged[(i+1)%len(merged)][0]+(knots[-1] if i==len(merged)-1 else 0)
                middle=[k+turn*knots[-1] for turn in (0,1) for k in knots[:-1] if end+1e-8<k+turn*knots[-1]<stop-1e-8]
                paths.append(([at(end),*[at(k) for k in middle],at(stop)],False))
        band['opening_cuts_m']=[list(pair) for pair in merged]
        for index,(points,closed) in enumerate(paths):
            facade=Facade(tuple(o+(lo if k==2 else 0) for k,o in enumerate(plane.origin)),right,forward)
            op=dict(id=band['id']+'_piece_'+str(index),band=band['id'],points=points,facade=asdict(facade),
                    width=p.projection+p.embed,depth=p.height,proud=p.height,closed=closed,slot=p.slot)
            create_trim(probe,**{k:v for k,v in op.items() if k not in ('id','band','facade')},facade=facade)
            op['world_centerline_m']=[facade.point(x,y,p.height/2) for x,y in points]
            operations.append(op)
    zones=[]
    for level in range(floors):
        start=level*floor_height;end=min((level+1)*floor_height,height-roof_cap_thickness)
        intervals=[(start,end)] if end>start else []
        for b in bands:
            low,high=b['z_range_m'];low-=opening_clearance;high+=opening_clearance;new=[]
            for a,c in intervals:
                if high<=a or low>=c:new.append((a,c))
                else:
                    if a<low:new.append((a,low))
                    if high<c:new.append((high,c))
            intervals=new
        zones.append(dict(floor=level,clear_z_intervals_m=intervals))
    parameters=dict(width=width,depth=depth,floors=floors,floor_height=floor_height,origin=plane.origin,yaw_degrees=yaw_degrees,
                    base=None if profiles[0] is None else asdict(profiles[0]),floor=None if profiles[1] is None else asdict(profiles[1]),
                    roof=None if profiles[2] is None else asdict(profiles[2]),base_offset=base_offset,floor_offset=floor_offset,
                    roof_offset=roof_offset,openings=clean,opening_clearance=opening_clearance,roof_cap_thickness=roof_cap_thickness)
    inset=profiles[2].embed if profiles[2] and abs(roof_offset)<1e-9 else 0.
    return dict(schema=1,parameters=parameters,scope='rectangular upright wall body; flat eave datum',
                datums=dict(wall_height_m=height,floor_levels_m=[n*floor_height for n in range(floors+1)],
                            origin=plane.origin,right=right,forward=forward),facades=facade_frames,bands=bands,
                assembly_seats=dict(wall_top_m=height-roof_cap_thickness,
                    roof_cap_local_bounds_m=[[inset,inset,height-roof_cap_thickness],[width-inset,depth-inset,height]] if roof_cap_thickness else None,
                    rule='Walls stop at cap underside; cap and top-anchored trim share eave top with disjoint plan areas. Avoid coplanar wall/trim/cap top faces.'),
                storey_opening_zones=zones,operations=operations,
                rules='Offsets from base-bottom / floor-center / roof-top; projection outward and embed inward from wall; opening cuts include clearance; rebuild derived placements on update')


def create_building_trim(b, width, depth, floors, floor_height=3., **options):
    """Plan then emit all building trim; returns plan with caller-local face IDs.

    Invalid dimensions/joins fail before any caller mesh writes. For updates,
    rebuild the building's owned trim mesh from new parameters into a fresh
    builder, then replace that owned mesh. This API never deletes scene content.
    """
    plan=plan_building_trim(width,depth,floors,floor_height,**options)
    for op in plan['operations']:
        args={k:op[k] for k in ('points','width','depth','proud','closed','slot')}
        op['roles']=create_trim(b,facade=Facade(**op['facade']),**args)['roles']
    return plan


def create_building_walls(b, plan, wall_depth=.22, *, wall_slot=0, reveal_slot=None):
    """Emit four miter-joined walls from a building trim plan/JSON parameters.

    Exterior UVs and aperture reveals retain create_wall's contract. Adjacent
    walls share inner/outer corner edges without square-end overlaps or internal
    caps; window/door holes must clear the corner depth. Plan and every wall are
    validated before caller writes. Returns per-facade face roles and wall depth.
    No roof cap/trim mesh, scene/files or existing objects are modified.
    """
    if plan.get('schema')!=1:raise ValueError('Expected building trim plan schema1')
    plan=plan_building_trim(**plan['parameters']);_positive(wall_depth,'wall depth')
    if 2*wall_depth>=min(plan['parameters']['width'],plan['parameters']['depth']):
        raise ValueError('Building wall depth consumes footprint')
    calls=[];probe=_TrimProbe()
    for name,row in plan['facades'].items():
        args=dict(width=row['width_m'],height=plan['assembly_seats']['wall_top_m'],depth=wall_depth,
                  openings=[Opening(**o) for o in plan['parameters']['openings'][name]],facade=Facade(**row['frame']),
                  wall_slot=wall_slot,reveal_slot=reveal_slot,miter_ends=True,end_caps=(False,False))
        create_wall(probe,**args);calls.append((name,args))
    return dict(wall_depth_m=wall_depth,joints='mitered shared edges; no internal caps',
                facades={name:create_wall(b,**args) for name,args in calls})


def _cross(a,b):return a[0]*b[1]-a[1]*b[0]
def _sub(a,b):return (a[0]-b[0],a[1]-b[1])


def _intersects(a,b,c,d):
    ab,cd=_sub(b,a),_sub(d,c);den=_cross(ab,cd)
    if abs(den)<1e-10:
        if abs(_cross(_sub(c,a),ab))>1e-10:return False
        axis=0 if abs(ab[0])>=abs(ab[1]) else 1
        return max(min(a[axis],b[axis]),min(c[axis],d[axis]))<min(max(a[axis],b[axis]),max(c[axis],d[axis]))-1e-9
    t=_cross(_sub(c,a),cd)/den;u=_cross(_sub(c,a),ab)/den
    return -1e-9<=t<=1+1e-9 and -1e-9<=u<=1+1e-9


def create_trim(b, points, *, facade=Facade(), width=.12, depth=.08, proud=.02,
                closed=False, miter_limit=4., slot=1):
    """Sweep one continuous trim ribbon along a planar local x/z centerline.

    Shared miter cross-sections meet exactly: no intersecting corner blocks or
    internal end caps. Supports facade/gable slopes and closed roof-plan loops
    by choosing the appropriate Facade plane. Open ends are square/capped.
    Rejects U-turns, excessive miters, consumed runs and self-crossing bands
    BEFORE writes. Caller splits nonplanar roof faces into explicit planes.
    Returns role ranges, exact joint edges, run lengths and miter extensions.
    """
    for value,label in ((width,'trim width'),(depth,'trim depth'),(miter_limit,'miter limit')):_positive(value,label)
    _positive(proud,'trim proud',zero=True);_slot(slot)
    if not isinstance(facade,Facade) or type(closed) is not bool:raise ValueError('Expected Facade/closed flag')
    points=[tuple(p) for p in points]
    if len(points)<(3 if closed else 2) or any(len(p)!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in p) for p in points):
        raise ValueError('Trim needs finite local x/z points')
    pairs=list(zip(points,points[1:]+points[:1] if closed else points[1:]))
    lengths=[math.dist(a,c) for a,c in pairs]
    if any(v<1e-6 for v in lengths):raise ValueError('Trim has zero-length/repeated endpoints')
    tangents=[((c[0]-a[0])/v,(c[1]-a[1])/v) for (a,c),v in zip(pairs,lengths)]
    left=[];right=[];extensions=[]
    for i,p in enumerate(points):
        if not closed and i in (0,len(points)-1):
            t=tangents[0 if i==0 else -1];offset=(-t[1]*width/2,t[0]*width/2)
        else:
            a,c=tangents[i-1],tangents[i%len(tangents)];den=1+a[0]*c[0]+a[1]*c[1]
            if den<1e-8:raise ValueError('Trim U-turn needs separate authored ends')
            offset=(-(a[1]+c[1])*width/2/den,(a[0]+c[0])*width/2/den)
        extension=math.hypot(*offset)
        if extension>miter_limit*width/2:raise ValueError('Trim corner exceeds miter limit')
        left.append((p[0]+offset[0],p[1]+offset[1]));right.append((p[0]-offset[0],p[1]-offset[1]));extensions.append(extension)
    for i,t in enumerate(tangents):
        j=(i+1)%len(points)
        if any(sum(v*k for v,k in zip(_sub(side[j],side[i]),t))<=1e-8 for side in (left,right)):
            raise ValueError('Trim width/corner consumes a run')
    # Boundary crossing rejects overlapping offset ribbons as well as centerlines.
    loops=[left,right] if closed else [left+right[::-1]]
    edges=[]
    for loop in loops:
        edges+=list(zip(loop,loop[1:]+loop[:1]))
    for i,(a,c) in enumerate(edges):
        for d,e in edges[:i]:
            if any(math.dist(x,y)<1e-8 for x in (a,c) for y in (d,e)):continue
            if _intersects(a,c,d,e):raise ValueError('Trim ribbon crosses or overlaps itself')
    roles={'front':[],'back':[],'sides':[],'ends':[]};u=[0.]
    for length in lengths:u.append(u[-1]+length)
    def emit(role,coords,uv):
        roles[role].append(len(b.faces));b.face([facade.point(*p) for p in coords],slot,(1,1,1,1),uv)
    for i in range(len(pairs)):
        j=(i+1)%len(points);a,c=left[i],right[i];d,e=right[j],left[j]
        front=[(*p,proud) for p in (a,c,d,e)];back=[(*p,proud-depth) for p in (a,c,d,e)]
        uv=[(u[i]/2.4,width/2.4),(u[i]/2.4,0),(u[i+1]/2.4,0),(u[i+1]/2.4,width/2.4)]
        emit('front',front,uv);emit('back',back[::-1],uv[::-1])
        emit('sides',[back[0],front[0],front[3],back[3]],[(u[i]/2.4,0),(u[i]/2.4,depth/2.4),(u[i+1]/2.4,depth/2.4),(u[i+1]/2.4,0)])
        emit('sides',[front[1],back[1],back[2],front[2]],[(u[i]/2.4,depth/2.4),(u[i]/2.4,0),(u[i+1]/2.4,0),(u[i+1]/2.4,depth/2.4)])
    if not closed:
        for i,reverse in ((0,False),(-1,True)):
            a,c=left[i],right[i];coords=[(*a,proud),(*a,proud-depth),(*c,proud-depth),(*c,proud)]
            if reverse:coords.reverse()
            emit('ends',coords,[(0,0),(0,depth/2.4),(width/2.4,depth/2.4),(width/2.4,0)])
    return dict(roles=roles,left=left,right=right,lengths_m=lengths,miter_extension_m=extensions,
                joints='shared cross-sections; no internal caps',closed=closed)


class _CanopyProbe:
    """Stage faces until the opening-clearance check succeeds."""

    def __init__(self):
        self.faces = []
        self.attributes = []

    def face(self, points, slot, color, uv=None):
        self.faces.append(points)
        self.attributes.append((slot, color, uv))


def _check_canopy_openings(faces, facade, openings, opening_facade, clearance):
    if not isinstance(opening_facade, Facade) or any(
        abs(a-b) > 1e-6 for a,b in zip((*facade.right, *facade.up), (*opening_facade.right, *opening_facade.up))
    ):
        raise ValueError('Canopy and opening facades must have matching right/up axes')

    def project(point):
        delta = tuple(a-b for a,b in zip(point, facade.origin))
        return tuple(sum(a*b for a,b in zip(delta, axis)) for axis in (facade.right, facade.up))

    projected = []
    for face in faces:
        xs,zs = zip(*(project(p) for p in face))
        projected.append((min(xs), min(zs), max(xs), max(zs)))
    for index, record in enumerate(openings, start=1):
        opening = record if isinstance(record, Opening) else Opening(**record)
        x,z = project(opening_facade.point(opening.x, opening.z, 0))
        x0,z0 = x-clearance, z-clearance
        x1,z1 = x+opening.width+clearance, z+opening.height+clearance
        if any(a < x1 and c > x0 and b < z1 and d > z0 for a,b,c,d in projected):
            raise ValueError(f'Canopy overlaps protected opening {index} in facade elevation')


def create_canopy(b, width, projection, *, facade=Facade(), style='sloped', rise=.45, drop=.3,
                  thickness=.06, supports='brackets', support_height=2.4, stripes=6,
                  roof_slot=0, edge_slot=1, support_slot=2, accent_slot=3,
                  protected_openings=(), opening_facade=None, opening_clearance=.025):
    """Append a varied mounting-plane canopy, without arranging a whole building.

    Forms: flat, sloped, gable, barrel or fabric (alternating strips/valance).
    Supports: brackets, posts or none. Facade origin is the rear roof/eave level;
    projection goes outward. Post height is measured down from its roof contact,
    not terrain-conformed; the building recipe supplies actual mounting height.
    Protected door/window Opening records use X/Z meters in opening_facade,
    which defaults to the canopy mount frame and must have matching axes. The
    projected face bounds, including fascia and supports, conservatively reserve
    their front elevation. An overlap rejects the canopy before appending faces.
    """
    for value,label in ((width,'canopy width'),(projection,'projection'),(thickness,'thickness'),(support_height,'support height')):_positive(value,label)
    for value,label in ((rise,'rise'),(drop,'drop')):_positive(value,label,zero=True)
    for slot in (roof_slot,edge_slot,support_slot,accent_slot):_slot(slot)
    if not isinstance(facade,Facade) or style not in ('flat','sloped','gable','barrel','fabric') or supports not in ('brackets','posts','none'):
        raise ValueError('Unknown canopy style/support or facade')
    if width<=.3 or projection<=.15 or thickness>=min(width,projection)/3 or (style in ('gable','barrel') and rise<=thickness):
        raise ValueError('Canopy dimensions consume roof/profile')
    if type(stripes) is not int or not 1<=stripes<=32:raise ValueError('Canopy stripes must be in1..32')
    _positive(opening_clearance, 'opening clearance', zero=True)
    output = b
    if protected_openings:
        b = _CanopyProbe()
    roles={};contacts=[]
    def roof_z(x,d):
        if style in ('sloped','fabric'):return -drop*d/projection
        if style=='gable':return rise*(1-abs(2*x/width-1))
        if style=='barrel':
            profile=[(width*(1-math.cos(j*math.pi/8))/2,rise*math.sin(j*math.pi/8)) for j in range(9)]
            for (a,z),(c,w) in zip(profile,profile[1:]):
                if a-1e-9<=x<=c+1e-9:return z+(w-z)*(x-a)/(c-a)
            raise ValueError('Canopy support outside roof span')
        return 0.
    if style in ('flat','sloped','fabric'):
        count=stripes if style=='fabric' else 1;front=-drop if style!='flat' else 0.
        for i in range(count):
            x=width*i/count;plane=Facade(facade.point(x,0,0),facade.outward,facade.up)
            outline=[(0,0),(projection,front),(projection,front-thickness),(0,-thickness)]
            roles[f'roof_{i}']=_prism(b,plane,outline,0,-width/count,roof_slot if i%2==0 else accent_slot)
            if style=='fabric':
                roles[f'valance_{i}']=_box(b,facade,(x,front-max(.2,thickness+.05),x+width/count,front-thickness),projection+.012,projection-.012,roof_slot if i%2==0 else accent_slot)
    else:
        top=[(0,0),(width/2,rise),(width,0)] if style=='gable' else [(width*(1-math.cos(j*math.pi/8))/2,rise*math.sin(j*math.pi/8)) for j in range(9)]
        outline=top+[(x,z-thickness) for x,z in reversed(top)]
        roles['roof']=_prism(b,facade,outline,projection,0,roof_slot)
    if style in ('flat','sloped'):
        z=roof_z(width/2,projection)
        roles['fascia']=_box(b,facade,(0,z-max(.12,thickness+.04),width,z-thickness),projection+.012,projection-.012,edge_slot)
    for i,x in enumerate((.10,width-.10)):
        if supports=='none':break
        if supports=='posts':
            rear,front=projection-.125,projection-.035;z=roof_z(x,projection-.08)-thickness
            base=min(roof_z(x,rear),roof_z(x,front))-thickness-support_height
            if style in ('sloped','fabric'):
                plane=Facade(facade.point(x,0,0),facade.outward,facade.up)
                outline=[(rear,base),(front,base),(front,roof_z(x,front)-thickness),(rear,roof_z(x,rear)-thickness)]
                roles[f'post_{i}']=_prism(b,plane,outline,.045,-.045,support_slot)
            else:
                xs=sorted({x-.045,x+.045,*([p[0] for p in top if x-.045<p[0]<x+.045] if style in ('gable','barrel') else [])})
                outline=[(xs[0],base),(xs[-1],base)]+[(a,roof_z(a,front)-thickness) for a in reversed(xs)]
                roles[f'post_{i}']=_prism(b,facade,outline,front,rear,support_slot)
            contacts.append(facade.point(x,z,projection-.08))
        else:
            reach=projection*.7;z=roof_z(x,reach)-thickness
            plane=Facade(facade.point(x,0,0),facade.outward,facade.up)
            roles[f'bracket_{i}']=_prism(b,plane,[(0,-.55),(reach,z),(0,-thickness)],.025,-.025,support_slot)
            contacts.append(facade.point(x,z,reach))
    if protected_openings:
        _check_canopy_openings(b.faces, facade, protected_openings,
                              facade if opening_facade is None else opening_facade, opening_clearance)
        start = len(output.faces)
        for points, attributes in zip(b.faces, b.attributes):
            output.face(points, *attributes)
        roles = {key:[start+i for i in indices] for key,indices in roles.items()}
    return dict(style=style,supports=supports,roles=roles,support_contacts=contacts,
                mount_origin=facade.origin,variation='explicit form, size, rise/drop, supports, stripe count and material slots')
