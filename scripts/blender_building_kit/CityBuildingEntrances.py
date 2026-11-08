"""Building wall openings, framed inserts and retained D103 entrance recipes.

Ordinary Python geometry; usable by Blender builders exposing faces and
face(points, slot, color, uv=None). No bpy, scene or file work on import/call.
Callers own mesh creation, materials, review and checked export. New create_*
operations use meters and explicit semantic slot indices; old D103 recipes
retain their accepted fixed coordinates/slots. Returned roles identify faces.
"""

from dataclasses import dataclass, asdict
import math


# Public accepted design values for callers; validation uses this same tuple.
DOOR_DESIGNS = ('flush', 'panelled', 'six_panel', 'half_glazed',
                'arched_glazed', 'full_glazed')


def _positive(value, name, zero=False):
    if not isinstance(value, (int, float)) or not math.isfinite(value) or (value < 0 if zero else value <= 0):
        raise ValueError(f'{name} must be finite and {"nonnegative" if zero else "positive"}')


def _slot(value):
    if type(value) is not int or value < 0:
        raise ValueError('Material slots must be nonnegative integers')


@dataclass(frozen=True)
class Facade:
    """Meter basis at exterior wall plane; right x up points outward.

    Supply an orthonormal basis instead of object scale/reflections. Wall
    thickness extends inward (negative depth). Default outward is local -Y.
    """
    origin: tuple = (0., 0., 0.)
    right: tuple = (1., 0., 0.)
    up: tuple = (0., 0., 1.)

    def __post_init__(self):
        for name in ('origin', 'right', 'up'):
            vector = tuple(getattr(self, name))
            if len(vector) != 3 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vector):
                raise ValueError('Facade vectors must contain three finite numbers')
            object.__setattr__(self, name, vector)
        dot = lambda a, b: sum(x*y for x, y in zip(a, b))
        if any(abs(dot(v, v)-1) > 1e-6 for v in (self.right, self.up)) or abs(dot(self.right, self.up)) > 1e-6:
            raise ValueError('Facade right/up must be orthogonal unit vectors; bake scale explicitly')

    @property
    def outward(self):
        a, b = self.right, self.up
        return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])

    def point(self, x, z, depth):
        return tuple(o+x*r+z*u+depth*n for o, r, u, n in zip(self.origin, self.right, self.up, self.outward))


@dataclass(frozen=True)
class Opening:
    """Shared rectangular rough hole/insert bounds in facade meters."""
    x: float
    z: float
    width: float
    height: float

    def __post_init__(self):
        _positive(self.width, 'opening width')
        _positive(self.height, 'opening height')
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (self.x, self.z)):
            raise ValueError('Opening x/z must be finite')

    @property
    def bounds(self):
        return (self.x, self.z, self.x+self.width, self.z+self.height)


def _face(b, facade, points, slot, color=(1, 1, 1, 1)):
    # Local planar UVs stay stable when the entire facade is rotated.
    a, c, d = points[:3]
    ab = [c[i]-a[i] for i in range(3)]
    ac = [d[i]-a[i] for i in range(3)]
    normal = (ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0])
    axis = max(range(3), key=lambda i: abs(normal[i]))
    axes = [i for i in range(3) if i != axis]
    b.face([facade.point(*p) for p in points], slot, color,
           [(p[axes[0]]/2.4, p[axes[1]]/2.4) for p in points])


def _box(b, facade, bounds, front, back, slot, color=(1, 1, 1, 1)):
    x0, z0, x1, z1 = bounds
    points = [(x0,z0,back),(x1,z0,back),(x1,z1,back),(x0,z1,back),
              (x0,z0,front),(x1,z0,front),(x1,z1,front),(x0,z1,front)]
    start = len(b.faces)
    for indices in ((0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)):
        _face(b, facade, [points[i] for i in indices], slot, color)
    return list(range(start, len(b.faces)))


def _prism(b, facade, outline, front, back, slot, color=(1,1,1,1)):
    """Extrude a simple planar x/z profile, dropping collapsed corner vertices."""
    clean=[]
    for p in outline:
        if not clean or math.dist(p,clean[-1])>1e-9: clean.append(p)
    if len(clean)>1 and math.dist(clean[0],clean[-1])<1e-9: clean.pop()
    area=sum(a[0]*c[1]-c[0]*a[1] for a,c in zip(clean,clean[1:]+clean[:1]))
    if len(clean)<3 or abs(area)<1e-12:return []
    if area<0:clean.reverse()
    start=len(b.faces)
    _face(b,facade,[(x,z,front) for x,z in clean],slot,color)
    _face(b,facade,[(x,z,back) for x,z in reversed(clean)],slot,color)
    for a,c in zip(clean,clean[1:]+clean[:1]):
        _face(b,facade,[(a[0],a[1],back),(c[0],c[1],back),(c[0],c[1],front),(a[0],a[1],front)],slot,color)
    return list(range(start,len(b.faces)))


def _beveled_panel(b, facade, bounds, thickness, slot):
    """Low-poly recessed infill with four bevel faces rather than applied trim."""
    x0,z0,x1,z1=bounds
    inset=min(.022,(x1-x0)*.08,(z1-z0)*.05)
    rim=-min(.003,thickness*.15);recess=-min(.014,thickness*.35);back=-thickness+.004
    outer=[(x0,z0,rim),(x1,z0,rim),(x1,z1,rim),(x0,z1,rim)]
    inner=[(x0+inset,z0+inset,recess),(x1-inset,z0+inset,recess),
           (x1-inset,z1-inset,recess),(x0+inset,z1-inset,recess)]
    rear=[(x,z,back) for x,z,_ in outer];start=len(b.faces)
    _face(b,facade,inner,slot);_face(b,facade,rear[::-1],slot)
    for i in range(4):
        j=(i+1)%4
        _face(b,facade,[outer[i],outer[j],inner[j],inner[i]],slot)
        _face(b,facade,[rear[i],rear[j],outer[j],outer[i]],slot)
    return list(range(start,len(b.faces)))


def create_wall(b, width, height, depth, openings=(), *, facade=Facade(), wall_slot=0, reveal_slot=None,
                miter_ends=False, end_caps=(True,True)):
    """Append a thick rectangular wall with actual empty rectangular holes.

    The same Opening records feed create_window/create_door. Grid subdivision
    emits front/back and exposed boundaries only, with continuous facade UVs;
    there are no internal cell faces or backing polygons across the apertures.
    Floor-reaching openings are supported. Openings must be disjoint, separated
    by positive wall and clear of the other three outer edges. Invalid input
    fails before appending any face. Returns named wall/reveal face ranges.
    This authors a wall panel; it does not Boolean-cut arbitrary existing meshes.
    miter_ends insets the two back endpoints by depth for45-degree corner joins.
    end_caps controls left/right outer ends only; joined building walls omit
    them to avoid internal duplicate surfaces. Aperture reveals stay unchanged.
    """
    for value, name in ((width, 'wall width'), (height, 'wall height'), (depth, 'wall depth')):
        _positive(value, name)
    _slot(wall_slot)
    reveal_slot = wall_slot if reveal_slot is None else reveal_slot
    _slot(reveal_slot)
    openings = tuple(openings)
    if not isinstance(facade, Facade) or any(not isinstance(o, Opening) for o in openings):
        raise ValueError('Expected Facade and Opening records')
    if type(miter_ends) is not bool or not isinstance(end_caps,(tuple,list)) or len(end_caps)!=2 or any(type(v) is not bool for v in end_caps):
        raise ValueError('Expected miter flag and two end-cap flags')
    if miter_ends and width<=2*depth:raise ValueError('Mitered wall depth consumes back face')
    for i, o in enumerate(openings):
        if not (o.x > 0 and o.z >= 0 and o.x+o.width < width and o.z+o.height < height):
            raise ValueError('Opening must fit wall interior; only bottom edge may reach wall boundary')
        if miter_ends and (o.x<=depth or o.x+o.width>=width-depth):
            raise ValueError('Opening must clear the mitered wall ends')
        for other in openings[:i]:
            if (o.x <= other.x+other.width and other.x <= o.x+o.width and
                    o.z <= other.z+other.height and other.z <= o.z+o.height):
                raise ValueError('Openings must not touch or overlap')
    xs = sorted({0, width, *(v for o in openings for v in (o.x, o.x+o.width))})
    zs = sorted({0, height, *(v for o in openings for v in (o.z, o.z+o.height))})
    solid = set()
    for i in range(len(xs)-1):
        for j in range(len(zs)-1):
            x, z = (xs[i]+xs[i+1])/2, (zs[j]+zs[j+1])/2
            if not any(o.x < x < o.x+o.width and o.z < z < o.z+o.height for o in openings):
                solid.add((i, j))
    roles = {'front': [], 'back': [], 'boundary': []}
    for i, j in sorted(solid):
        x0, x1, z0, z1 = xs[i], xs[i+1], zs[j], zs[j+1]
        front = [(x0,z0,0),(x1,z0,0),(x1,z1,0),(x0,z1,0)]
        def back_x(x):return depth if miter_ends and x==0 else width-depth if miter_ends and x==width else x
        back = [(back_x(x0),z0,-depth),(back_x(x1),z0,-depth),(back_x(x1),z1,-depth),(back_x(x0),z1,-depth)]
        for name, points in (('front', front), ('back', back[::-1])):
            roles[name].append(len(b.faces)); _face(b, facade, points, wall_slot)
        sides = [((i-1,j),[back[0],front[0],front[3],back[3]]),
                 ((i+1,j),[front[1],back[1],back[2],front[2]]),
                 ((i,j-1),[front[0],back[0],back[1],front[1]]),
                 ((i,j+1),[back[3],front[3],front[2],back[2]])]
        for side,(neighbor, points) in enumerate(sides):
            if neighbor not in solid:
                if (side==0 and i==0 and not end_caps[0]) or (side==1 and i==len(xs)-2 and not end_caps[1]):continue
                roles['boundary'].append(len(b.faces)); _face(b, facade, points, reveal_slot)
    return dict(facade=asdict(facade), openings=[asdict(o) for o in openings], roles=roles,
                miter_ends=miter_ends,end_caps=list(end_caps))


def create_entrance_hall(b, opening, wall_depth, *, facade=Facade(), width=1.4, depth=2.6,
                         height=2.35, return_depth=1.4, wing=1.6, turn='right',
                         agent_radius=.25, agent_height=1.75, clearance=.15, frame_width=.09,
                         wall_slot=0, floor_slot=0, ceiling_slot=0):
    """Append a plain L-shaped entrance recess and return a hidden walking path.

    Meters in the same Facade/Opening basis as the door. Walls face inward;
    floor/ceiling are nonoverlapping rectangles. The host owns the mouth reveal.
    Caller must remove any existing floor faces over floor_regions_m before
    assembly: this does not cut arbitrary source meshes or author native paths.
    No Blender/file writes. Invalid fit/occlusion fails before appending faces.
    """
    if not isinstance(opening,Opening) or not isinstance(facade,Facade) or turn not in ('left','right'):
        raise ValueError('Expected Opening/Facade and left/right hall turn')
    for value,name in ((wall_depth,'wall depth'),(width,'hall width'),(depth,'hall depth'),
                       (height,'hall height'),(return_depth,'return depth'),(wing,'hall wing'),
                       (agent_radius,'agent radius'),(agent_height,'agent height'),(clearance,'hall clearance'),
                       (frame_width,'door frame width')):
        _positive(value,name)
    for slot in (wall_slot,floor_slot,ceiling_slot):_slot(slot)
    half=width/2;mouth=opening.width/2;lane=(return_depth+depth)/2
    hidden=half+wing-agent_radius-clearance
    # Sightline from the far mouth edge to the far/near envelope corner must
    # hit the return beyond its inside corner. This covers the complete mouth,
    # rather than a chosen exterior camera or only the proxy's center.
    shadow=-mouth+(hidden-agent_radius+mouth)*return_depth/(lane+agent_radius)
    if (width<opening.width or opening.height-frame_width-.008<agent_height+.05 or
        opening.width-2*frame_width-.008<2*agent_radius+.10 or height<opening.height or
        wall_depth>=return_depth or lane-agent_radius-clearance<=return_depth or
        lane+agent_radius+clearance>=depth or half<=agent_radius+clearance or
        shadow<=half+.025):
        raise ValueError('Hall must fit walking envelope and hide its endpoint behind the return')
    sign=1 if turn=='right' else -1;cx=opening.x+mouth;floor=opening.z
    def point(u,d,z):return facade.point(cx+sign*u,floor+z,-d)
    roles={'walls':[],'floor':[],'ceiling':[]}
    def face(points,role,slot):
        if sign<0:points=list(reversed(points))
        roles[role].append(len(b.faces))
        _face(b,facade,[(cx+sign*u,floor+z,-d) for u,d,z in points],slot)
    # Continuous perimeter, excluding the front wall owned by the host facade.
    edges=[((-half,depth),(-half,wall_depth)),((half,wall_depth),(half,return_depth)),
           ((half,return_depth),(half+wing,return_depth)),
           ((half+wing,return_depth),(half+wing,depth)),((half+wing,depth),(-half,depth))]
    for (u0,d0),(u1,d1) in edges:
        face([(u0,d0,0),(u0,d0,height),(u1,d1,height),(u1,d1,0)],'walls',wall_slot)
    regions=[(-mouth,0,mouth,wall_depth),(-half,wall_depth,half,depth),
             (half,return_depth,half+wing,depth)]
    for i,(u0,d0,u1,d1) in enumerate(regions):
        corners=[(u0,d0,0),(u1,d0,0),(u1,d1,0),(u0,d1,0)]
        face(corners,'floor',floor_slot)
        if i:face([(u,d,height) for u,d,z in reversed(corners)],'ceiling',ceiling_slot)
    path=[point(0,0,0),point(0,lane,0),point(hidden,lane,0)]
    return dict(parameters=dict(opening=asdict(opening),wall_depth=wall_depth,facade=asdict(facade),
                width=width,depth=depth,height=height,return_depth=return_depth,wing=wing,turn=turn,
                agent_radius=agent_radius,agent_height=agent_height,clearance=clearance,frame_width=frame_width,
                wall_slot=wall_slot,floor_slot=floor_slot,ceiling_slot=ceiling_slot),roles=roles,
                walk_path_m=path,anchors=dict(Threshold=path[0],Turn=path[1],Hidden=path[2]),
                floor_regions_m=regions,
                floor_regions_basis='(u0,inward0,u1,inward1), u from opening center toward selected turn',
                hide_shadow_margin_m=shadow-half,
                floor_owner='hall; remove host faces over floor_regions_m',
                lifecycle='Join exterior approach at Threshold; remove/create citizen only at Hidden, behind return. Native consumer required.')


def _fit(opening, facade, wall_depth, frame_width, frame_proud):
    if not isinstance(opening, Opening) or not isinstance(facade, Facade):
        raise ValueError('Expected Opening and Facade records')
    for value, name in ((wall_depth, 'wall depth'), (frame_width, 'frame width')):
        _positive(value, name)
    _positive(frame_proud, 'frame proud', zero=True)
    if min(opening.width, opening.height) <= 2*frame_width:
        raise ValueError('Frame consumes the opening')


def _frame(b, facade, bounds, width, front, back, slot, bottom=None):
    x0,z0,x1,z1 = bounds
    bottom = width if bottom is None else bottom
    parts = {'left':(x0,z0+bottom,x0+width,z1-width), 'right':(x1-width,z0+bottom,x1,z1-width),
             'top':(x0,z1-width,x1,z1)}
    if bottom > 0:
        parts['bottom'] = (x0,z0,x1,z0+bottom)
    return {key:_box(b,facade,rect,front,back,slot) for key,rect in parts.items()}


def create_window(b, opening, wall_depth, *, facade=Facade(), frame_width=.075, frame_proud=.02,
                  glass_recess=.04, glass_thickness=.006, overlap=.01, columns=1, rows=1,
                  mullion_width=.04, frame_slot=1, glass_slot=4):
    """Append a fitted frame, closed pane and optional regular mullion grid.

    Opening is the rough wall hole; jambs lie inside it. Butt-joined frame rails
    do not overlap at corners. Positive overlap hides pane edges behind rails;
    glass_recess is measured inward from the frame front, not from wall plane.
    No wall/backing face is created. Glass WindowMask alpha is zero, all other
    faces alpha one. Returns clear-aperture bounds and named face ranges.
    All parameter checks precede builder mutation; callers own slot materials.
    """
    _fit(opening,facade,wall_depth,frame_width,frame_proud)
    _slot(frame_slot); _slot(glass_slot)
    for value,name in ((glass_recess,'glass recess'),(glass_thickness,'glass thickness'),(mullion_width,'mullion width')):
        _positive(value,name)
    _positive(overlap,'overlap',zero=True)
    if overlap >= frame_width or glass_recess+glass_thickness >= wall_depth+frame_proud:
        raise ValueError('Glass must overlap within frame width and fit inside frame depth')
    if any(type(v) is not int or not 1 <= v <= 32 for v in (columns, rows)):
        raise ValueError('Window rows/columns must be integers in 1..32')
    x0,z0,x1,z1 = opening.bounds
    clear = (x0+frame_width,z0+frame_width,x1-frame_width,z1-frame_width)
    a,c,d,e = clear
    if (columns > 1 and mullion_width >= (d-a)/columns) or (rows > 1 and mullion_width >= (e-c)/rows):
        raise ValueError('Mullions consume the clear opening')
    roles = _frame(b,facade,opening.bounds,frame_width,frame_proud,-wall_depth,frame_slot)
    pane = (a-overlap,c-overlap,d+overlap,e+overlap)
    roles['glass'] = _box(b,facade,pane,frame_proud-glass_recess,
                          frame_proud-glass_recess-glass_thickness,glass_slot,(1,1,1,0))
    cuts = [a]+[a+(d-a)*i/columns for i in range(1,columns)]+[d]
    for i, mid in enumerate(cuts[1:-1], 1):
        roles[f'column_{i}'] = _box(b,facade,(mid-mullion_width/2,c,mid+mullion_width/2,e),
                                   frame_proud,-wall_depth,frame_slot)
    # Horizontal bars butt against vertical bars, avoiding coplanar cross patches.
    for i in range(1,rows):
        mid = c+(e-c)*i/rows
        for j,(left,right) in enumerate(zip(cuts,cuts[1:])):
            rect = (left+(mullion_width/2 if j else 0),mid-mullion_width/2,
                    right-(mullion_width/2 if j < columns-1 else 0),mid+mullion_width/2)
            roles[f'row_{i}_{j}'] = _box(b,facade,rect,frame_proud,-wall_depth,frame_slot)
    return dict(opening=asdict(opening), facade=asdict(facade), clear_aperture=clear,
                pane_bounds=pane, overlap_m=overlap, roles=roles)


def create_door(b, opening, wall_depth, *, facade=Facade(), frame_width=.09, frame_proud=.02,
                leaves=1, glazed=False, leaf_thickness=.04, clearance=.004, threshold_height=0.,
                frame_slot=1, leaf_slot=1, glass_slot=4, design=None, panel_slot=None):
    """Append a single/double solid or glazed closed door and matching jambs.

    Shares the rough Opening with create_wall. Default jamb has no bottom rail;
    an explicit threshold may raise its bottom. Leaves have side/top/bottom and
    center-seam clearances; glazed leaves have real panes, without solid backing.
    design selects flush, panelled, six_panel, half_glazed, arched_glazed or
    full_glazed (the public DOOR_DESIGNS tuple). 'glazed' is not a design;
    glazed=True is a separate low-level flag used only when design is None.
    None retains that flag behavior. Independent leaf/panel/glass slots support
    material mixes. Returns leaf bounds, jamb roles and nested leaf roles. No animation/Boolean
    edits, scene saves or production adoption. Dimensions are meters.
    """
    _fit(opening,facade,wall_depth,frame_width,frame_proud)
    panel_slot = leaf_slot if panel_slot is None else panel_slot
    for slot in (frame_slot,leaf_slot,glass_slot,panel_slot): _slot(slot)
    for value,name in ((leaf_thickness,'leaf thickness'),(clearance,'leaf clearance')): _positive(value,name)
    _positive(threshold_height,'threshold height',zero=True)
    if type(leaves) is not int or leaves not in (1,2) or type(glazed) is not bool:
        raise ValueError('Door requires one/two leaves and a boolean glazed choice')
    design = ('full_glazed' if glazed else 'flush') if design is None else design
    if design not in DOOR_DESIGNS:
        raise ValueError(f'Unknown door design {design!r}; expected one of: ' + ', '.join(DOOR_DESIGNS))
    x0,z0,x1,z1 = opening.bounds
    bottom = z0+threshold_height
    top = z1-frame_width
    leaf_width = (opening.width-2*frame_width-clearance*(leaves+1))/leaves
    leaf_height = top-bottom-2*clearance
    stile = min(frame_width, .06)
    if min(leaf_width,leaf_height) <= 2*stile or leaf_thickness+.02 >= wall_depth+frame_proud:
        raise ValueError('Door leaves/threshold consume available aperture or depth')
    # Glazed leaf is delegated to the same validated window operation.
    if design in ('half_glazed','arched_glazed','full_glazed') and leaf_thickness <= .012:
        raise ValueError('Glazed leaf needs depth for glass and recess')
    if design in ('panelled','six_panel','half_glazed','arched_glazed') and leaf_thickness <= .012:
        raise ValueError('Recessed panels need at least12mm leaf depth')
    roles = _frame(b,facade,opening.bounds,frame_width,frame_proud,-wall_depth,frame_slot,threshold_height)
    leaf_records = []
    for i in range(leaves):
        left = x0+frame_width+clearance+i*(leaf_width+clearance)
        rect = (left,bottom+clearance,left+leaf_width,top-clearance)
        front = frame_proud-.02
        if design == 'full_glazed':
            # Offset facade plane to the leaf front; frame has no additional proud.
            leaf_facade = Facade(facade.point(0,0,front),facade.right,facade.up)
            o = Opening(left,bottom+clearance,leaf_width,leaf_height)
            record = create_window(b,o,leaf_thickness,facade=leaf_facade,frame_width=stile,frame_proud=0.,
                                   glass_recess=leaf_thickness/3,glass_thickness=.004,overlap=min(.01,stile/2),
                                   frame_slot=leaf_slot,glass_slot=glass_slot)
        elif design == 'six_panel':
            local=Facade(facade.point(0,0,front),facade.right,facade.up)
            parts=_frame(b,local,rect,stile,0,-leaf_thickness,leaf_slot)
            lx,lz,rx,rz=rect;a,c,d,e=lx+stile,lz+stile,rx-stile,rz-stile
            middle=(a+d)/2;seam=min(stile,(d-a)/6,(e-c)/9)
            parts['center_stile']=_box(b,local,(middle-seam/2,c,middle+seam/2,e),0,-leaf_thickness,leaf_slot)
            for row in range(3):
                low=c+(e-c)*row/3;high=c+(e-c)*(row+1)/3
                for col,(left,right) in enumerate(((a,middle-seam/2),(middle+seam/2,d))):
                    if row<2:
                        parts[f'rail_{row}_{col}']=_box(b,local,(left,high-seam/2,right,high+seam/2),0,-leaf_thickness,leaf_slot)
                    panel=(left,low+(seam/2 if row else 0),right,high-(seam/2 if row<2 else 0))
                    parts[f'panel_{row}_{col}']=_beveled_panel(b,local,panel,leaf_thickness,panel_slot)
            record=dict(roles=parts)
        elif design in ('panelled','half_glazed','arched_glazed'):
            local = Facade(facade.point(0,0,front),facade.right,facade.up)
            parts = _frame(b,local,rect,stile,0,-leaf_thickness,leaf_slot)
            lx,lz,rx,rz = rect
            mid = lz+leaf_height*.45
            overlap = min(.005,stile/2)
            parts['cross_rail'] = _box(b,local,(lx+stile,mid-stile/2,rx-stile,mid+stile/2),
                                       0,-leaf_thickness,leaf_slot)
            parts['lower_panel'] = _box(b,local,(lx+stile-overlap,lz+stile-overlap,rx-stile+overlap,mid-stile/2+overlap),
                                        -.004,-leaf_thickness+.004,panel_slot)
            upper = (lx+stile-overlap,mid+stile/2-overlap,rx-stile+overlap,rz-stile+overlap)
            if design=='arched_glazed':
                a,c,d,e=lx+stile,mid+stile/2,rx-stile,rz-stile
                half=(d-a)/2;center=(a+d)/2;rise=min((e-c)*.5,half);spring=e-rise
                bead=min(.035,stile*.6,(d-a)*.05,(e-c)*.06)
                outer=[(center+half*math.cos(j*math.pi/8),spring+rise*math.sin(j*math.pi/8)) for j in range(9)]
                inner=[(center+(half-bead)*math.cos(j*math.pi/8),spring+(rise-bead)*math.sin(j*math.pi/8)) for j in range(9)]
                glass_arc=[(center+(half-bead+overlap)*math.cos(j*math.pi/8),spring+(rise-bead+overlap)*math.sin(j*math.pi/8)) for j in range(9)]
                profile=[(center-half+bead-overlap,c+bead-overlap),(center+half-bead+overlap,c+bead-overlap)]+glass_arc
                parts['glass']=_prism(b,local,profile,-leaf_thickness/3,-leaf_thickness/3-.004,glass_slot,(1,1,1,0))
                for j in range(8):
                    parts[f'arch_bead_{j}']=_prism(b,local,[outer[j],outer[j+1],inner[j+1],inner[j]],0,-leaf_thickness,leaf_slot)
                    parts[f'arch_spandrel_{j}']=_prism(b,local,[outer[j+1],outer[j],(outer[j][0],e),(outer[j+1][0],e)],0,-leaf_thickness,panel_slot)
                for key,area in {'arch_left':(a,c,a+bead,spring),'arch_right':(d-bead,c,d,spring),'arch_bottom':(a,c,d,c+bead)}.items():
                    parts[key]=_box(b,local,area,0,-leaf_thickness,leaf_slot)
            else:
                parts['glass' if design=='half_glazed' else 'upper_panel'] = _box(
                    b,local,upper,-leaf_thickness/3,-leaf_thickness/3-.004 if design=='half_glazed' else -leaf_thickness+.004,
                    glass_slot if design=='half_glazed' else panel_slot,(1,1,1,0) if design=='half_glazed' else (1,1,1,1))
            record = dict(roles=parts)
        else:
            record = dict(roles={'panel':_box(b,facade,rect,front,front-leaf_thickness,leaf_slot)})
        leaf_records.append(dict(bounds=rect,**record))
    return dict(opening=asdict(opening),facade=asdict(facade),roles=roles,leaves=leaf_records,
                leaf_clearance_m=clearance,threshold_height_m=threshold_height)


def glass(b,x0,x1,y,z0,z1):
    b.face([(x0,y,z0),(x1,y,z0),(x1,y,z1),(x0,y,z1)],4,(1,1,1,0),[(0,0),(1,0),(1,1),(0,1)])


def framed_glass(b,x0,x1,y,z0,z1,frame=.075):
    glass(b,x0+frame,x1-frame,y+.035,z0+frame,z1-frame)
    for x in (x0+frame/2,x1-frame/2):
        b.box((x,y,(z0+z1)/2),(frame,.10,z1-z0),1)
    for z in (z0+frame/2,z1-frame/2):
        b.box(((x0+x1)/2,y,z),(x1-x0,.10,frame),1)


def store_entrance(b,variant):
    """Append a storefront door, glazing and approach to the supplied mesh builder."""
    start=len(b.faces)
    floor=.16
    top=floor+2.35
    y=-7.16 if variant!=3 else -7.84
    pair=2.50 if variant!=2 else 2.60
    # Door leaves, center seam and obvious pull bars on swing-door variants.
    for x0,x1 in ((-pair/2,-.025),(.025,pair/2)):
        framed_glass(b,x0,x1,y,floor,top)
        if variant!=2:
            x=-.15 if x1<0 else .15
            b.box((x,y-.10,1.35),(.045,.075,.56),1)
            for z in (1.12,1.58):b.box((x,y-.065,z),(.08,.12,.04),1)
        if variant==1:
            b.box(((x0+x1)/2,y-.012,floor+.17),(x1-x0-.12,.08,.28),1)
    style=('double glass with transom','double glass with sidelights/kickplates',
           'automatic sliding pair','glazed double-door vestibule')[variant]
    width=pair
    if variant in (1,2):
        side=.60 if variant==1 else .95
        for x0,x1 in ((-pair/2-side,-pair/2),(pair/2,pair/2+side)):
            framed_glass(b,x0,x1,y,floor,top)
        width=pair+side*2
    if variant==0:
        framed_glass(b,-1.38,1.38,y,top+.06,top+.72)
        width=2.76
    if variant==2:
        b.box((0,y-.035,top+.16),(width+.18,.24,.26),1)
        # Door-guide rail and a compact sensor over the central overlap.
        b.box((0,y-.18,top+.20),(.28,.12,.10),1)
        b.box((0,y-.065,floor+.015),(pair+.08,.18,.035),1)
    else:
        b.box((0,y,top+.03),(width+.14,.18,.13),1)
    if variant==3:
        # Side glazing joins the forward door plane back to the actual facade.
        for x in (-1.40,1.40):
            points=[(x,y,floor+.08),(x,-7.02,floor+.08),(x,-7.02,top-.05),(x,y,top-.05)]
            if x<0:points.reverse()
            b.face(points,4,(1,1,1,0),[(0,0),(1,0),(1,1),(0,1)])
            for py in (y,-7.02):b.box((x,py,(floor+top)/2),(.10,.10,top-floor),1)
            for z in (floor+.05,top-.03):b.box((x,(y-7.02)/2,z),(.10,-7.02-y,.10),1)
        b.box((0,(y-7.02)/2,top+.05),(2.95,-7.02-y+.12,.16),1)
        width=2.95
    b.box((0,y-.10,floor+.015),(width+.08,.32,.03),1)
    return dict(style=style,door_leaf_count=2,personnel_clear_width_m=pair-.20,
                door_height_m=2.35,floor_m=floor,door_front_y_m=y,
                faces=list(range(start,len(b.faces))),
                detail_bounds_m=[[-width/2-.15,y-.26,0],[width/2+.15,-7.0,3.40]])


def personnel_door(b,variant):
    """Append a personnel entrance and its approach metadata using existing slots."""
    start=len(b.faces)
    x,y,floor=5.20,-7.15,.16
    width,height=1.10,2.05
    b.box((x,y+.025,floor+height/2),(width,.13,height),1)
    for px in (x-width/2-.055,x+width/2+.055):
        b.box((px,y-.03,floor+height/2),(.11,.18,height+.08),4)
    b.box((x,y-.03,floor+height+.055),(width+.22,.18,.11),4)
    b.box((x,y-.11,floor+.02),(width+.22,.36,.04),1)
    # Steel lever, latch plate and visible hinge barrels.
    b.box((x+.37,y-.09,1.12),(.06,.055,.20),4)
    b.box((x+.30,y-.13,1.16),(.23,.075,.045),1)
    for z in (.55,1.65):b.box((x-.56,y-.05,z),(.035,.07,.13),1)
    if variant in (0,2,3):
        framed_glass(b,x-.24,x+.24,y-.09,1.36,1.95,.045)
    # The personnel path reaches the same front road edge beside freight access.
    b.box((x,-8.73,.08),(1.45,3.34,.16),1)
    return dict(center_x_m=x,front_y_m=y,width_m=width,height_m=height,floor_m=floor,
                faces=list(range(start,len(b.faces))),path_bounds_m=[[x-.725,-10.40,0],[x+.725,-7.06,.16]])


def freight_door(b,x,width,floor,height,roller=False,glazed=False):
    """Append framed freight-door geometry with optional roller or glazed detailing."""
    start=len(b.faces)
    y=-7.17
    b.box((x,y+.055,floor+height/2),(width,.16,height),1)
    for px in (x-width/2-.09,x+width/2+.09):
        b.box((px,y-.04,floor+height/2),(.18,.23,height+.05),1)
    b.box((x,y-.04,floor+height+.09),(width+.36,.24,.18),1)
    spacing=.25 if roller else .78
    z=floor+spacing
    while z<floor+height-.10:
        if not (glazed and floor+height-.96<z<floor+height-.38):
            b.box((x,y-.035,z),(width-.10,.055,.035 if roller else .055),1)
        z+=spacing
    if glazed:
        count=4 if width>4 else 2
        for i in range(count):
            center=x+(i-(count-1)/2)*width/(count+.4)
            framed_glass(b,center-.39,center+.39,y-.09,floor+height-.90,floor+height-.45,.04)
    b.box((x,y-.07,floor+.025),(width+.18,.26,.05),1)
    return dict(center_x_m=x,width_m=width,height_m=height,floor_m=floor,front_y_m=y,
                style='roller shutter' if roller else 'glazed sectional' if glazed else 'sectional',
                faces=list(range(start,len(b.faces))))


def industrial_entrances(b,variant):
    """Add industrial door variants to the builder and return their entrance records."""
    person=personnel_door(b,variant)
    start=len(b.faces)
    dock=None
    if variant==3:
        delivery=[freight_door(b,x,2.60,.08,4.45,glazed=True) for x in (-1.47,1.47)]
        b.box((0,-7.22,2.33),(.20,.22,4.50),1)
        style='two workshop sectional bays'
    else:
        floor=1.05 if variant==2 else .08
        delivery=[freight_door(b,0,5.65,floor,3.65 if variant==2 else 4.55,
                               roller=variant in (1,2),glazed=variant==0)]
        style=('glazed sectional garage','warehouse roller shutter','raised loading dock')[variant]
    if variant==2:
        b.box((0,-8.26,.525),(6.40,2.42,1.05),1)
        b.box((0,-9.49,1.06),(5.60,.16,.04),1)
        # Dock bumpers are attached to the vertical front apron, outside steps.
        for x in (-2.40,2.40):b.box((x,-9.56,.72),(.34,.20,.58),1)
        for i in range(5):
            step=.21*(i+1)
            b.box((-4.8425+i*.365,-8.30,step/2),(.365,1.10,step),1)
        dock=dict(platform_top_m=1.05,platform_bounds_m=[[-3.20,-9.47,0],[3.20,-7.05,1.05]],
                  step_count=5,step_rise_m=.21)
    else:
        # Low protective bollards flank freight access, clear of the person door.
        for x in (-3.38,3.38):b.box((x,-8.02,.46),(.24,.24,.92),2)
    return dict(style=style,personnel=person,freight=delivery,dock=dock,
                freight_faces=list(range(start,len(b.faces))),
                detail_bounds_m=[[-5.35,-10.55,0],[6.0,-6.9,5.30]])
