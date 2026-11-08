"""Explicit facade/service detail planning, geometry and editable Blender prefabs.

Planning/geometry use ordinary Python and do not touch scenes/files. The lazy
Blender adapter reuses the opening prefab lifecycle; callers own placement,
saves and export. Foundation bands remain CityBuildingDetails trim operations.
Static surface details add no wall cuts, plumbing, simulation or native assets.
"""
import copy
from dataclasses import asdict
import math
import re

from .CityBuildingEntrances import Facade, Opening, _box, _prism
from .CityBuildingShell import _Geometry


FACADE_DETAIL_KINDS = ('panel_seams', 'downpipe', 'service_box', 'wall_vent', 'bollard')
_DEFAULTS = {
    'panel_seams': dict(spacing=1.2, z=.35, height=None, width=.035, depth=.025),
    'downpipe': dict(z=0., width=.12, height=3., depth=.14),
    'service_box': dict(z=.5, width=.85, height=1.15, depth=.24),
    'wall_vent': dict(z=1.5, width=1.2, height=.65, depth=.09),
    'bollard': dict(z=0., width=.16, height=1., depth=.16, offset=.7),
}


def _number(value, label, zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or (value < 0 if zero else value <= 0):
        raise ValueError(label + ' must be finite and ' + ('nonnegative' if zero else 'positive'))


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _expand(rect, margin):
    return [rect[0]-margin, rect[1]-margin, rect[2]+margin, rect[3]+margin]


def _top_at(profile, x):
    a,b=next((a,b) for a,b in zip(profile,profile[1:]) if a[0]-1e-9<=x<=b[0]+1e-9)
    return a[1]+(b[1]-a[1])*(x-a[0])/(b[0]-a[0])


def facade_top_from_shell(shell_plan, side, section='base', *, projection=0.):
    """Return width/height/top_profile at the actual shell roof UNDERSIDE.

    Profile z is relative to that section's facade ground datum. projection is
    the detail's outward proud depth: side-eave ceilings follow the underside
    slope there. Gable ends include the apex. No arbitrary mesh inspection.
    """
    _number(projection,'projection',True)
    if side not in ('front','right','back','left'): raise ValueError('Unknown facade side')
    matches=[s for s in shell_plan['sections'] if s['id']==section]
    if len(matches)!=1: raise ValueError('Unknown shell section')
    p=matches[0]['parameters'];z=p['floors']*p['floor_height']
    span=p['width'] if side in ('front','back') else p['depth']
    gable=p['roof']=='gable';end=(side in ('front','back'))==(p['ridge_axis']=='y')
    if gable and end:
        profile=[[0,z],[span/2,z+math.tan(math.radians(p['roof_pitch']))*span/2],[span,z]]
    else:
        top=z-math.tan(math.radians(p['roof_pitch']))*projection if gable else z
        profile=[[0,top],[span,top]]
    return dict(width=span,height=max(v[1] for v in profile),top_profile=profile)


def _roof_clipped(rect, profile):
    """Clip a rectangle to each linear ceiling segment, preserving angled ends."""
    polygons=[]
    for a,b in zip(profile,profile[1:]):
        lo=max(rect[0],a[0]);hi=min(rect[2],b[0])
        if hi-lo<1e-8: continue
        poly=[(lo,rect[1]),(hi,rect[1]),(hi,rect[3]),(lo,rect[3])];out=[]
        signed=lambda p:p[1]-(a[1]+(b[1]-a[1])*(p[0]-a[0])/(b[0]-a[0]))
        for p,q in zip(poly,poly[1:]+poly[:1]):
            dp,dq=signed(p),signed(q)
            if dp<=1e-9:out.append(list(p))
            if (dp<0<dq) or (dq<0<dp):
                t=dp/(dp-dq);out.append([p[0]+t*(q[0]-p[0]),p[1]+t*(q[1]-p[1])])
        if len(out)>=3 and abs(sum(p[0]*q[1]-q[0]*p[1] for p,q in zip(out,out[1:]+out[:1])))>1e-9:polygons.append(out)
    return polygons


def plan_facade_details(width, height, elements, *, facade=Facade(), openings=(), exclusions=(), clearance=.12, top_profile=None):
    """Plan explicit details on ONE upright facade, before geometry/scene writes.

    Meters: x is facade left-to-right, z is height from facade ground datum.
    elements require unique id/kind. panel_seams uses spacing/z/height/width/depth;
    other kinds require center x and accept z/width/height/depth. bollard alone
    accepts outward offset, and requires z=0. Defaults are in _DEFAULTS above.
    openings/exclusions are Opening records or x/z/width/height dictionaries.
    Seams split around their expanded rectangles and all solid detail bounds;
    other details reject aperture/exclusion/each-other overlap. This conservative
    2D reservation does not inspect arbitrary host geometry or traffic routes.
    Caller must supply exclusions for existing signs, canopies and other props.
    Vertical facade up must be +Z, so bollard/pipe ground and height are explicit.
    Returns a portable plan, including exact facade-local rectangles and roles.
    top_profile is an ordered [x,z] ceiling spanning 0..width (default flat at
    height). panel_seams height=None follows it; a numeric height caps the run.
    facade_top_from_shell derives profiles for existing flat/gable shell plans.
    """
    _number(width, 'facade width'); _number(height, 'facade height')
    _number(clearance, 'clearance', True)
    if not isinstance(facade, Facade) or math.dist(facade.up, (0, 0, 1)) > 1e-8:
        raise ValueError('Expected upright Facade with up=+Z')
    if not isinstance(elements, (list, tuple)) or not elements:
        raise ValueError('Supply a nonempty detail list')
    profile=copy.deepcopy(top_profile) if top_profile is not None else [[0.,height],[width,height]]
    if not isinstance(profile,(list,tuple)) or len(profile)<2: raise ValueError('Top profile needs x/z points')
    for point in profile:
        if not isinstance(point,(list,tuple)) or len(point)!=2: raise ValueError('Top profile needs x/z points')
        _number(point[0],'profile x',True);_number(point[1],'profile z')
    if profile[0][0]!=0 or profile[-1][0]!=width or any(a[0]>=b[0] for a,b in zip(profile,profile[1:])) or max(p[1] for p in profile)>height:
        raise ValueError('Top profile must span facade in increasing x within height')
    blocked=[]; clean=[]
    for values in (openings, exclusions):
        if not isinstance(values, (list, tuple)):
            raise ValueError('Opening/exclusion lists required')
        rows=[]
        for value in values:
            o=value if isinstance(value, Opening) else Opening(**value)
            if o.x < 0 or o.z < 0 or o.x+o.width > width or o.z+o.height > height:
                raise ValueError('Opening/exclusion exceeds facade')
            rows.append(asdict(o)); blocked.append(_expand(list(o.bounds), clearance))
        clean.append(rows)
    placements=[]; ids=set(); solids=[]
    for item in elements:
        if not isinstance(item, dict) or item.get('kind') not in FACADE_DETAIL_KINDS:
            raise ValueError('Detail kind must be one of: '+', '.join(FACADE_DETAIL_KINDS))
        kind=item['kind']; label=item.get('id')
        if not isinstance(label, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', label) or label in ids:
            raise ValueError('Detail ids must be unique portable names')
        ids.add(label)
        allowed={'id', 'kind', *_DEFAULTS[kind]}
        if kind!='panel_seams': allowed.add('x')
        if set(item)-allowed or (kind!='panel_seams' and 'x' not in item):
            raise ValueError('Unsupported/missing fields for '+kind)
        p={**_DEFAULTS[kind], **copy.deepcopy(item)}
        for key in set(p)-{'id', 'kind'}:
            if kind=='panel_seams' and key=='height' and p[key] is None: continue
            _number(p[key], key, key in ('x', 'z'))
        x=p.get('x', 0); z=p['z']; w=p['width']; h=p['height']; d=p['depth']
        if kind=='panel_seams':
            if p['spacing'] < 2*w or w < .01 or d < .005 or z>=height or (h is not None and z+h > height):
                raise ValueError('Seam dimensions/spacing exceed facade')
            rect=None
        else:
            extra=.04 if kind in ('downpipe','service_box') else .06 if kind=='bollard' else 0
            top=.04 if kind=='service_box' else 0
            rect=[x-w/2-extra, z, x+w/2+extra, z+h+top]
            ceiling=min([_top_at(profile,max(0,min(width,x))) for x in (rect[0],rect[2])]+[p[1] for p in profile if rect[0]<p[0]<rect[2]])
            if rect[0] < 0 or rect[2] > width or rect[3] > ceiling:
                raise ValueError('Detail exceeds facade bounds')
            if min(w, d) < .03 or h < .3 or (kind=='downpipe' and h < .8):
                raise ValueError('Detail dimensions too small for its parts')
            if kind=='service_box' and (w < .35 or h < .45 or d < .08):
                raise ValueError('Service cabinet dimensions consume frame/handle')
            if kind=='wall_vent' and (w < .35 or h < .3):
                raise ValueError('Wall vent dimensions consume grille')
            if kind=='bollard' and (z!=0 or p['offset'] <= d/2+.1):
                raise ValueError('Bollard must start at ground, clear of wall')
            if any(_overlap(rect, r) for r in blocked) or any(_overlap(rect, _expand(r, clearance)) for r in solids):
                raise ValueError('Detail intersects aperture/exclusion/another detail: '+label)
            solids.append(rect)
        placements.append(dict(id=label, kind=kind, parameters=p, bounds_m=rect))
    reservations=blocked+[_expand(r, clearance) for r in solids]
    for row in placements:
        if row['kind']!='panel_seams': continue
        p=row['parameters']; strips=[]; polygons=[]; n=1
        while n*p['spacing']+p['width']/2 < width:
            x=n*p['spacing']; n+=1
            intervals=[(p['z'], p['z']+p['height'] if p['height'] is not None else height)]
            for r in reservations:
                if x+p['width']/2 <= r[0] or x-p['width']/2 >= r[2]: continue
                intervals=[part for a,b in intervals for part in ((a,min(b,r[1])),(max(a,r[3]),b)) if part[1]-part[0] > 1e-7]
            for a,b in intervals:
                for poly in _roof_clipped([x-p['width']/2,a,x+p['width']/2,b],profile):
                    polygons.append(poly);strips.append([min(p[0] for p in poly),min(p[1] for p in poly),max(p[0] for p in poly),max(p[1] for p in poly)])
        row['strips_m']=strips
        row['profiles_m']=polygons
    params=dict(width=width, height=height, elements=copy.deepcopy(list(elements)), facade=asdict(facade),
                openings=clean[0], exclusions=clean[1], clearance=clearance,top_profile=profile)
    return dict(schema=1, parameters=params, placements=placements,
                limits='Static surface decoration; explicit reservations; no wall cuts, terrain or working service systems')


def create_facade_details(b, width, height, elements, **options):
    """Append validated metric/UV geometry; reject the whole set before writes.

    Builder uses the existing face(points,slot,color,uv) contract. Fixed five-role
    slots: frame=0, leaf=1, panel=2, glass=3 (unused), hardware=4. Every element
    has named face roles. Complete geometry is buffered before caller mutation.
    """
    plan=plan_facade_details(width, height, elements, **options)
    f=Facade(**plan['parameters']['facade']); g=_Geometry(); groups=[]
    for row in plan['placements']:
        p=row['parameters']; roles={}; x=p.get('x',0); z=p['z']; w=p['width']; h=p['height']; d=p['depth']
        def box(role, rect, front, back, slot):
            roles.setdefault(role, []).extend(_box(g,f,rect,front,back,slot))
        if row['kind']=='panel_seams':
            for poly in row['profiles_m']: roles.setdefault('seams',[]).extend(_prism(g,f,poly,d,-.006,0))
        elif row['kind']=='downpipe':
            box('pipe',[x-w/2,z+.16,x+w/2,z+h],d,.025,1)
            box('outlet',[x-w/2,z+.08,x+w/2,z+.22],d+.22,.025,1)
            for level in (z+.4,z+h-.2):
                box('wall_clamps',[x-w/2-.04,level-.03,x+w/2+.04,level+.03],d+.02,-.012,0)
        elif row['kind']=='service_box':
            box('cabinet',[x-w/2,z,x+w/2,z+h],d,-.012,2)
            box('door',[x-w/2+.04,z+.04,x+w/2-.04,z+h-.04],d+.012,d,1)
            box('rain_hood',[x-w/2-.04,z+h,x+w/2+.04,z+h+.04],d+.06,-.012,0)
            box('handle',[x+w/2-.13,z+h*.45,x+w/2-.09,z+h*.65],d+.055,d+.012,4)
        elif row['kind']=='wall_vent':
            box('backplate',[x-w/2,z,x+w/2,z+h],.02,-.012,4)
            for rect in ([x-w/2,z,x-w/2+.04,z+h],[x+w/2-.04,z,x+w/2,z+h],
                         [x-w/2+.04,z,x+w/2-.04,z+.04],[x-w/2+.04,z+h-.04,x+w/2-.04,z+h]):
                box('frame',rect,d,-.012,0)
            for i in range(1,7):
                level=z+.04+(h-.08)*i/7
                box('louvers',[x-w/2+.04,level-.015,x+w/2-.04,level+.015],d,.02,1)
        else:
            offset=p['offset']
            box('foot',[x-w/2-.06,z,x+w/2+.06,z+.06],offset+d/2+.06,offset-d/2-.06,0)
            bevel=min(.025,w/4)
            outline=[(x-w/2,z+.06),(x+w/2,z+.06),(x+w/2,z+h-bevel),
                     (x+w/2-bevel,z+h),(x-w/2+bevel,z+h),(x-w/2,z+h-bevel)]
            roles['post']=_prism(g,f,outline,offset+d/2,offset-d/2,2)
            box('stripe',[x-w/2,z+h*.65,x+w/2,z+h*.75],offset+d/2+.002,offset-d/2-.002,4)
        groups.append(dict(id=row['id'], kind=row['kind'], roles=roles))
    start=len(b.faces)
    for points,slot,color,uv in zip(g.faces,g.slots,g.colors,g.uvs): b.face(points,slot,color,uv)
    for group in groups:
        group['roles']={k:[i+start for i in values] for k,values in group['roles'].items()}
    return dict(plan=plan, elements=groups)


def create_facade_details_prefab(name, width, height, elements, materials, **options):
    """Create one fresh editable static detail set using the shared lifecycle.

    Same arguments/reservations as plan_facade_details. Caller supplies five
    material roles, owns parenting/saving, and chooses a fresh object/collection
    name. Recipe kind is facade_details; hardware.elements contains face roles.
    Use one-element lists for independent cabinets/pipes or a whole-facade set.
    """
    from .CityBuildingOpeningPrefabs import _finish, add_assembly_helpers
    g=_Geometry(); report=create_facade_details(g,width,height,elements,**options)
    if not g.faces: raise ValueError('Detail set has no exposed geometry after clipping')
    prefab=_finish(name,g,list(range(len(g.faces))),[],materials,
                   dict(kind='facade_details',**report['plan']['parameters']),report)
    add_assembly_helpers(prefab, {'Mount':Facade(**report['plan']['parameters']['facade'])})
    return prefab
