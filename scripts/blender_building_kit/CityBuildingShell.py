"""Rectangular exterior shells, stacked sections and flat/gable caps.

Ordinary Python planning/geometry has no scene or file side effects. Builders
expose faces and face(points, slot, color, uv=None), like the opening helpers.
create_building_shell_prefab lazily imports Blender and creates only fresh
editable assemblies. Callers own saves, previews, checked exports and placement.
No interiors, native integration, fracture data or automatic source replacement.
"""
import copy
import json
import math
import re

from .CityBuildingEntrances import (
    Facade, Opening, _prism, _positive, create_door, create_window,
)
from .CityBuildingDetails import plan_building_trim, create_building_walls


class _Geometry:
    """In-memory transaction buffer; never imports Blender."""
    def __init__(self):
        self.faces, self.slots, self.colors, self.uvs = [], [], [], []

    def face(self, points, slot, color, uv=None):
        self.faces.append(points)
        self.slots.append(slot)
        self.colors.append(color)
        self.uvs.append(uv)


def _number(value, label, zero=False):
    if isinstance(value, bool):
        raise ValueError(label + ' must be numeric, not boolean')
    _positive(value, label, zero=zero)


def _terrace_cells(rect, holes, xs=(), ys=()):
    """Partition a rectangular cap around disjoint child footprints, no overlaps."""
    xs = sorted({rect[0], rect[2], *(v for h in holes for v in (h[0], h[2])), *(v for v in xs if rect[0]<v<rect[2])})
    ys = sorted({rect[1], rect[3], *(v for h in holes for v in (h[1], h[3])), *(v for v in ys if rect[1]<v<rect[3])})
    return [[x0, y0, x1, y1] for x0, x1 in zip(xs, xs[1:])
            for y0, y1 in zip(ys, ys[1:])
            if not any(h[0] <= (x0+x1)/2 <= h[2] and h[1] <= (y0+y1)/2 <= h[3] for h in holes)]


def plan_building_shell(width, depth, *, floors=1, floor_height=3., wall_depth=.22,
                        roof='gable', roof_pitch=30., ridge_axis='y', overhang=.3,
                        roof_thickness=.16, openings=(), towers=(), rooftop_elements=()):
    """Return a portable metric plan; reject the whole specification before writes.

    Base origin is exterior front-left (0,0,0); front=-Y, up=+Z. Floor indices
    are zero-based. Each opening is {floor,side,kind,x,z,width,height}, with z
    relative to its floor. Optional door design/leaves and window columns/rows
    use the existing insert APIs. Door design is flush, panelled, six_panel,
    half_glazed, arched_glazed or full_glazed (CityBuildingEntrances.DOOR_DESIGNS).
    'glazed' is not a design; the low-level glazed boolean is not a shell field.
    Openings must fit within one storey.

    towers is an ordered list of named section dictionaries: id, parent
    (default 'base'), offset=[x,y] relative to parent, width/depth and optional
    floors/floor_height/roof/roof_pitch/ridge_axis/overhang/roof_thickness/openings.
    Each parent must precede children and have a flat roof. Children sit at its
    cap's TOP, strictly inset; siblings and their roof overhangs cannot touch.
    A gable terminates a stack. Sections have no internal rooms or floor slabs.
    Flat cap thickness adds to each section's wall height before the next base.
    rooftop_elements optionally places explicit chimney/HVAC/hatch/vent source
    details by section-local center; the separate rooftop helper validates fit.
    """
    _number(wall_depth, 'wall depth')
    if not isinstance(towers,(list,tuple)) or not isinstance(openings,(list,tuple)):
        raise ValueError('towers/openings must be portable lists')
    base = dict(id='base', parent=None, offset=[0., 0.], width=width, depth=depth,
                floors=floors, floor_height=floor_height, roof=roof, roof_pitch=roof_pitch,
                ridge_axis=ridge_axis, overhang=overhang, roof_thickness=roof_thickness, openings=openings)
    defaults = dict(floors=1, floor_height=floor_height, roof='gable', roof_pitch=roof_pitch,
                    ridge_axis=ridge_axis, overhang=overhang, roof_thickness=roof_thickness, openings=[])
    specs = [base]
    allowed = {'id', 'parent', 'offset', 'width', 'depth', *defaults}
    for tower in towers:
        if not isinstance(tower, dict) or set(tower)-allowed or not {'id','width','depth'} <= set(tower):
            raise ValueError('Tower needs id/width/depth and only documented section fields')
        specs.append({**defaults, 'parent':'base', 'offset':[0.,0.], **copy.deepcopy(tower)})
    sections, by_id = [], {}
    for spec in specs:
        label = spec['id']
        if not isinstance(label, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', label) or label in by_id:
            raise ValueError('Section ids must be unique portable identifiers; base is reserved')
        for key in ('width','depth','floor_height','roof_thickness'):
            _number(spec[key], key)
        _number(spec['overhang'], 'overhang', zero=True)
        if type(spec['floors']) is not int or spec['floors'] < 1:
            raise ValueError('floors must be a positive integer')
        if 2*wall_depth >= min(spec['width'], spec['depth']):
            raise ValueError('Wall depth consumes section footprint')
        if spec['roof'] not in ('flat','gable') or spec['ridge_axis'] not in ('x','y'):
            raise ValueError('Roof must be flat/gable and ridge_axis x/y')
        _number(spec['roof_pitch'], 'roof pitch')
        if spec['roof_pitch'] >= 75:
            raise ValueError('Roof pitch must be greater than zero and below 75 degrees')
        offset = spec['offset']
        if not isinstance(offset, (list,tuple)) or len(offset) != 2:
            raise ValueError('offset must contain parent-local x/y')
        for value in offset:
            _number(value, 'offset', zero=True)
        x, y, z = 0., 0., 0.
        if spec['parent'] is not None:
            parent = by_id.get(spec['parent'])
            if parent is None or parent['parameters']['roof'] != 'flat':
                raise ValueError('Parent must precede child and have a flat cap')
            p = parent['parameters']
            o = spec['overhang']
            if not (offset[0]-o > 0 and offset[1]-o > 0 and
                    offset[0]+spec['width']+o < p['width'] and offset[1]+spec['depth']+o < p['depth']):
                raise ValueError('Child footprint and roof must be strictly inset inside parent')
            x, y = parent['origin_m'][0]+offset[0], parent['origin_m'][1]+offset[1]
            z = parent['roof_top_m']
        top = z+spec['floors']*spec['floor_height']
        finish = top+spec['roof_thickness']
        if spec['roof'] == 'gable':
            cross_span = spec['width'] if spec['ridge_axis'] == 'y' else spec['depth']
            finish += math.tan(math.radians(spec['roof_pitch']))*cross_span/2
            if math.tan(math.radians(spec['roof_pitch']))*spec['overhang'] >= spec['floor_height']:
                raise ValueError('Gable overhang descends below the top storey')
        normalized = []
        holes = {side:[] for side in ('front','right','back','left')}
        for item in spec['openings']:
            keys = {'floor','side','kind','x','z','width','height','design','leaves','columns','rows'}
            if not isinstance(item,dict) or set(item)-keys:
                raise ValueError('Opening contains unsupported fields')
            row = dict(floor=0, **item) if 'floor' not in item else dict(item)
            if type(row['floor']) is not int or not 0 <= row['floor'] < spec['floors']:
                raise ValueError('Opening floor must exist in its section')
            if row.get('side') not in holes or row.get('kind') not in ('door','window'):
                raise ValueError('Opening needs a valid side and door/window kind')
            if not {'x','z','width','height'} <= set(row):
                raise ValueError('Opening needs x/z/width/height')
            for key in ('x','z','width','height'):
                _number(row[key], 'opening '+key, zero=key in ('x','z'))
            if row['z']+row['height'] >= spec['floor_height']:
                raise ValueError('Opening must end below its storey top')
            optional = {'design','leaves'} if row['kind']=='door' else {'columns','rows'}
            if (set(row) & {'design','leaves','columns','rows'})-optional:
                raise ValueError('Opening options do not match its kind')
            o = Opening(row['x'], row['z']+row['floor']*spec['floor_height'], row['width'], row['height'])
            holes[row['side']].append(o)
            normalized.append(row)
        spec = dict(spec, offset=list(offset), openings=normalized)
        trim = plan_building_trim(spec['width'], spec['depth'], spec['floors'], spec['floor_height'],
                                  origin=(x,y,z), base=None, floor=None, roof=None,
                                  roof_cap_thickness=0, openings=holes)
        # Existing wall and insert validators run without touching any caller data.
        probe = _Geometry()
        create_building_walls(probe, trim, wall_depth)
        for row in normalized:
            opening = Opening(row['x'], row['z']+row['floor']*spec['floor_height'], row['width'], row['height'])
            kwargs = {k:row[k] for k in ('design','leaves','columns','rows') if k in row}
            (create_door if row['kind']=='door' else create_window)(probe, opening, wall_depth, **kwargs)
        rect = [x,y,x+spec['width'],y+spec['depth']]
        expanded = [x-spec['overhang'],y-spec['overhang'],rect[2]+spec['overhang'],rect[3]+spec['overhang']]
        for sibling in sections:
            if sibling['parameters']['parent'] == spec['parent'] and spec['parent'] is not None:
                other = sibling['roof_bounds_m']
                if not (expanded[2] < other[0] or expanded[0] > other[2] or expanded[3] < other[1] or expanded[1] > other[3]):
                    raise ValueError('Sibling sections and roof envelopes must be separated')
        section = dict(id=label, parameters=spec, origin_m=[x,y,z], footprint_m=rect,
                       roof_bounds_m=expanded, wall_top_m=top, roof_top_m=finish,
                       floor_levels_m=[z+i*spec['floor_height'] for i in range(spec['floors']+1)],
                       wall_plan=trim)
        sections.append(section)
        by_id[label] = section
    for section in sections:
        children = [s['footprint_m'] for s in sections if s['parameters']['parent']==section['id']]
        section['terrace_cells_m'] = _terrace_cells(section['roof_bounds_m'], children) if section['parameters']['roof']=='flat' else []
    parameters = dict(width=width,depth=depth,floors=floors,floor_height=floor_height,wall_depth=wall_depth,
                      roof=roof,roof_pitch=roof_pitch,ridge_axis=ridge_axis,overhang=overhang,
                      roof_thickness=roof_thickness,openings=copy.deepcopy(base['openings']),towers=copy.deepcopy(list(towers)),
                      rooftop_elements=copy.deepcopy(rooftop_elements))
    plan=dict(schema=1,units='meters/degrees',parameters=parameters,sections=sections,
              limits='Exterior only; inset stacks on flat caps; no rooms, floor slabs, valleys or fracture data')
    plan['rooftop_elements']=[]
    if rooftop_elements:
        from .CityBuildingRooftops import plan_rooftop_placements
        plan['rooftop_elements']=plan_rooftop_placements(plan,rooftop_elements)
    elif not isinstance(rooftop_elements,(list,tuple)):
        raise ValueError('Rooftop elements must be a portable list')
    return plan


def _flat_cap(b, section):
    """Emit top/bottom cells and ONLY exposed perimeter/reveal edges."""
    cells = section['terrace_cells_m']
    low, high = section['wall_top_m'], section['roof_top_m']
    edges = {}
    start = len(b.faces)
    for x0,y0,x1,y1 in cells:
        ring = [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
        for z, points in ((high,ring),(low,ring[::-1])):
            b.face([(x,y,z) for x,y in points],1,(1,1,1,1),[(x/2.4,y/2.4) for x,y in points])
        for a,c in zip(ring,ring[1:]+ring[:1]):
            key = tuple(sorted((a,c)))
            if key in edges:
                del edges[key]
            else:
                edges[key] = (a,c)
    for a,c in edges.values():
        points = [(a[0],a[1],low),(c[0],c[1],low),(c[0],c[1],high),(a[0],a[1],high)]
        b.face(points,1,(1,1,1,1),[(0,low),(math.dist(a,c),low),(math.dist(a,c),high),(0,high)])
    return list(range(start,len(b.faces)))


def _shell_geometry(plan, inserts, rooftop_details=True):
    b = _Geometry()
    components, opening_records = [], []
    def component(name, start):
        components.append(dict(id=name,faces=list(range(start,len(b.faces)))))
    for section in plan['sections']:
        p = section['parameters']
        start = len(b.faces)
        create_building_walls(b,section['wall_plan'],plan['parameters']['wall_depth'],wall_slot=2,reveal_slot=2)
        component(section['id']+'_Walls',start)
        if p['roof']=='flat':
            start = len(b.faces)
            _flat_cap(b,section)
            component(section['id']+'_FlatRoof',start)
        else:
            x,y,z = section['origin_m']
            w,d = p['width'],p['depth']
            cross,run = (w,d) if p['ridge_axis']=='y' else (d,w)
            frame = Facade((x,y,0)) if p['ridge_axis']=='y' else Facade((x+w,y,0),(0,1,0))
            top,slope,o,t = section['wall_top_m'],math.tan(math.radians(p['roof_pitch'])),p['overhang'],p['roof_thickness']
            ridge,eave = top+slope*cross/2,top-slope*o
            # One connected chevron cross section: both roof slopes share ridge
            # vertices. Thickness is vertical; underside touches wall/eave datum.
            outline = [(-o,eave),(cross/2,ridge),(cross+o,eave),
                       (cross+o,eave+t),(cross/2,ridge+t),(-o,eave+t)]
            start = len(b.faces)
            _prism(b,frame,outline,o,-run-o,1)
            component(section['id']+'_GableRoof',start)
            sides = ('front','back') if p['ridge_axis']=='y' else ('right','left')
            for side in sides:
                start = len(b.faces)
                facade = Facade(**section['wall_plan']['facades'][side]['frame'])
                h = p['floors']*p['floor_height']
                _prism(b,facade,[(0,h),(cross,h),(cross/2,h+slope*cross/2)],0,-plan['parameters']['wall_depth'],2)
                component(section['id']+'_Gable_'+side,start)
        for i,row in enumerate(p['openings']):
            opening = Opening(row['x'],row['z']+row['floor']*p['floor_height'],row['width'],row['height'])
            frame = Facade(**section['wall_plan']['facades'][row['side']]['frame'])
            record = dict(id=section['id']+'_Opening_'+str(i),kind=row['kind'],opening=opening.__dict__,
                          facade=frame.__dict__,options={k:row[k] for k in ('design','leaves','columns','rows') if k in row})
            opening_records.append(record)
            if inserts:
                start = len(b.faces)
                slots = dict(frame_slot=0,glass_slot=3)
                if row['kind']=='door':
                    slots.update(leaf_slot=1,panel_slot=2)
                (create_door if row['kind']=='door' else create_window)(b,opening,plan['parameters']['wall_depth'],
                    facade=frame,**record['options'],**slots)
                component(record['id'],start)
    if rooftop_details and plan['rooftop_elements']:
        from .CityBuildingRooftops import create_rooftop_element
        for element in plan['rooftop_elements']:
            start=len(b.faces)
            create_rooftop_element(b,**element['plan']['parameters'])
            component('Rooftop_'+element['id'],start)
    return b,components,opening_records


def create_building_shell(b, width, depth, **parameters):
    """Append a static closed-pose shell atomically; slots match prefab ROLES.

    Slots: frame=0, roof/door leaf=1, wall/panel=2, glass=3, hardware=4.
    Face groups are absolute indices into caller faces. For articulated inserts
    use create_building_shell_prefab instead; it retains the existing prefabs.
    """
    plan = plan_building_shell(width,depth,**parameters)
    geometry,components,openings = _shell_geometry(plan,True)
    offset = len(b.faces)
    for i,points in enumerate(geometry.faces):
        b.face(points,geometry.slots[i],geometry.colors[i],geometry.uvs[i])
    for component in components:
        component['faces'] = [i+offset for i in component['faces']]
    return dict(plan=plan,components=components,openings=openings)


class BuildingShellPrefab:
    """Fresh Blender source root, named shell branches and opening controllers."""
    def __init__(self,root,components,openings,recipe,rooftops=None):
        self.root,self.components,self.openings,self.recipe = root,components,openings,recipe
        self.rooftops=rooftops or []

    def write_recipe(self,path):
        """Write a NEW JSON recipe; rebuild with recipe['parameters'] and materials."""
        with open(path,'x',encoding='utf-8') as stream:
            json.dump(self.recipe,stream,indent=2)
            stream.write('\n')


def create_building_shell_prefab(name, width, depth, materials, *, rooftop_materials=None, **parameters):
    """Create editable Blender5 source, no file saves or existing-object edits.

    Uses existing five-role material bindings (frame,leaf,panel,glass,hardware):
    leaf colors the roof, panel colors walls. Shell walls/caps/gables are named
    branches; door/window roots retain independent parts, pivots and recipes.
    Openings use swing doors and fixed windows; callers may control their source
    parts through the returned opening controllers. Moving a root moves its full
    hierarchy. On failure, remove only data created during this transaction.
    """
    import bpy
    from .CityBuildingOpeningPrefabs import (
        _finish, _material_check, create_door_prefab, create_window_prefab,
    )
    _material_check(materials)
    rooftop_materials=materials if rooftop_materials is None else rooftop_materials
    _material_check(rooftop_materials)
    plan = plan_building_shell(width,depth,**parameters)
    geometry,groups,records = _shell_geometry(plan,False,rooftop_details=False)
    if not isinstance(name,str) or not name or any(o.name==name or o.name.startswith(name+'_') for o in bpy.data.objects) or name in bpy.data.collections:
        raise ValueError('Choose a fresh nonempty assembly name/prefix')
    previous = {kind:set(getattr(bpy.data,kind)) for kind in ('objects','meshes','collections')}
    try:
        collection = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collection)
        root = bpy.data.objects.new(name,None)
        collection.objects.link(root)
        components,controllers,rooftops = [],[],[]
        for group in groups:
            part = _Geometry()
            for i in group['faces']:
                part.face(geometry.faces[i],geometry.slots[i],geometry.colors[i],geometry.uvs[i])
            prefab = _finish(name+'_'+group['id'],part,list(range(len(part.faces))),[],materials,
                             dict(kind='building_shell_component',id=group['id']))
            prefab.root.parent = root
            components.append(prefab.root)
        for record in records:
            constructor = create_door_prefab if record['kind']=='door' else create_window_prefab
            options = dict(record['options'])
            if record['kind']=='window':
                options['motion'] = 'fixed'
            prefab = constructor(name+'_'+record['id'],Opening(**record['opening']),plan['parameters']['wall_depth'],
                                 materials,facade=Facade(**record['facade']),**options)
            prefab.root.parent = root
            controllers.append(prefab)
        if plan['rooftop_elements']:
            from .CityBuildingRooftops import create_rooftop_element_prefab
            for element in plan['rooftop_elements']:
                prefab=create_rooftop_element_prefab(name+'_Rooftop_'+element['id'],materials=rooftop_materials,**element['plan']['parameters'])
                prefab.root.parent=root
                rooftops.append(prefab)
        recipe = dict(schema=1,kind='building_shell',parameters=plan['parameters'],plan=plan,
                      components=[o.name for o in components],openings=[p.root.name for p in controllers],rooftops=[p.root.name for p in rooftops])
        root['CityBuildingShellRecipe'] = json.dumps(recipe)
        bpy.context.view_layer.update()
        return BuildingShellPrefab(root,components,controllers,recipe,rooftops)
    except Exception:
        for kind in ('objects','collections','meshes'):
            data = getattr(bpy.data,kind)
            for item in list(data):
                if item not in previous[kind]:
                    data.remove(item,do_unlink=True)
        raise
