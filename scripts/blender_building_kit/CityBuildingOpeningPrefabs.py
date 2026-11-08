"""Blender opening prefabs and shared building-assembly recipe/helper lifecycle.

Explicit create_*_prefab calls create a fresh collection, root, stationary frame
and pivot-local moving meshes in the current scene. No files, imports, global
preferences or existing objects are changed. Uses CityBuildingEntrances geometry;
callers save the blend/library and own export/native integration. Metadata is
plain JSON (meters/radians, world-space axes at root identity). Blender5.0.
"""
import json
import math
import bpy
from mathutils import Vector,Matrix
from .CityGarageGeometry import sectional_pose
from .CityBuildingEntrances import (
    Facade, Opening, create_window, create_door, _fit, _frame, _box,
)

ROLES = ('frame', 'leaf', 'panel', 'glass', 'hardware')


class _Geometry:
    def __init__(self):
        self.faces, self.slots, self.colors, self.uvs = [], [], [], []

    def face(self, points, slot, color, uv=None):
        self.faces.append(points); self.slots.append(slot)
        self.colors.append(color); self.uvs.append(uv)


def _indices(roles):
    return sorted(i for group in roles.values() for i in group)


def make_materials(prefix, *, leaf='wood', frame='metal', panel=None):
    """Create explicit Blender PBR bindings for five roles; no native materials.

    wood/metal/paint are opaque choices; glass uses transmission and hardware
    uses metal. Materials are reusable across multiple prefab instances. Caller
    owns the names/lifetime. Wood grain is procedural along local UV height.
    """
    choices = {'wood':(.32,.12,.035,0.,.48), 'metal':(.34,.40,.46,1.,.27),
               'paint':(.66,.68,.62,0.,.5), 'glass':(.20,.53,.65,0.,.12)}
    panel = leaf if panel is None else panel
    if any(v not in ('wood','metal','paint') for v in (leaf,frame,panel)):
        raise ValueError('Opaque palette choices are wood, metal or paint')
    result = {}
    for role,kind in zip(ROLES,(frame,leaf,panel,'glass','metal')):
        m = bpy.data.materials.new(prefix+'_'+role+'_'+kind); m.use_nodes = True
        shader = m.node_tree.nodes.get('Principled BSDF'); r,g,b,metal,rough = choices[kind]
        m.diffuse_color = (r,g,b,1); shader.inputs['Base Color'].default_value = (r,g,b,1)
        shader.inputs['Metallic'].default_value = metal; shader.inputs['Roughness'].default_value = rough
        if kind == 'glass':
            shader.inputs['Transmission Weight'].default_value = 1
            shader.inputs['IOR'].default_value = 1.45
        if kind == 'wood':
            nodes,links = m.node_tree.nodes,m.node_tree.links
            uv=nodes.new('ShaderNodeTexCoord'); scale=nodes.new('ShaderNodeVectorMath');scale.operation='MULTIPLY'
            scale.inputs[1].default_value=(90,3,1);links.new(uv.outputs['UV'],scale.inputs[0])
            noise=nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=1
            links.new(scale.outputs['Vector'],noise.inputs['Vector'])
            ramp=nodes.new('ShaderNodeValToRGB')
            ramp.color_ramp.elements[0].color=(r*.42,g*.42,b*.42,1)
            ramp.color_ramp.elements[1].color=(r*1.3,g*1.3,b*1.3,1)
            links.new(noise.outputs['Fac'],ramp.inputs[0]);links.new(ramp.outputs['Color'],shader.inputs['Base Color'])
        m['CityOpeningMaterialRole']=role; m['CityOpeningMaterialType']=kind; result[role]=m
    return result


class OpeningPrefab:
    """Root, meshes and portable motion recipe. set_open never accumulates drift."""
    def __init__(self, root, parts, recipe):
        self.root, self.parts, self.recipe = root, parts, recipe

    def set_open(self, amount, *, frame=None):
        """Set normalized openness0..1, optionally keyframe every part transform.

        Uses exact pivot-local rotation/track displacement from the closed pose.
        Root transforms remain caller-owned. Keyframes use Blender's default
        easing; callers may retime them. Refuses nonfinite/out-of-range state.
        """
        if not isinstance(amount,(int,float)) or not math.isfinite(amount) or not 0 <= amount <= 1:
            raise ValueError('Openness must be finite in 0..1')
        for obj,part in zip(self.parts,self.recipe['parts']):
            if part['mode']=='sectional':
                spec=part['sectional'];inward,z,angle=sectional_pose(amount=amount,**spec)
                closed=(spec['index']+.5)*spec['height']/spec.get('count',24)
                obj.location=Vector(part['pivot'])+Vector(part['track_up'])*(z-closed)-Vector(part['track_outward'])*inward
            else:
                obj.location = Vector(part['pivot'])+Vector(part['travel'])*amount
                angle=part['angle']*amount
            obj.rotation_mode='AXIS_ANGLE';obj.rotation_axis_angle=(angle,*part['axis'])
            if frame is not None:
                obj.keyframe_insert('location',frame=frame)
                obj.keyframe_insert('rotation_axis_angle',frame=frame)
        self.root['openness']=amount
        bpy.context.view_layer.update()

    def write_recipe(self, path):
        """Write portable parameters/part pivots/material roles to a NEW JSON file."""
        with open(path,'x',encoding='utf-8') as stream:
            json.dump(self.recipe,stream,indent=2);stream.write('\n')


def load_prefab(root):
    """Restore control of a saved/appended/copied prefab root, preserving names.

    Child part indices survive Blender's automatic duplicate-name suffixes.
    Only directly parented parts are controlled; unrelated scene objects stay
    untouched. The root may be translated/rotated/scaled by the caller.
    """
    recipe=json.loads(root['CityOpeningRecipe'])
    if recipe.get('schema')!=1:
        raise ValueError('Unsupported opening prefab recipe')
    parts=[]
    for i in range(len(recipe['parts'])):
        matches=[o for o in root.children if o.get('CityOpeningPart')==i]
        if len(matches)!=1:raise ValueError('Prefab must have exactly one mesh per moving part')
        parts.append(matches[0])
    return OpeningPrefab(root,parts,recipe)


def fabricate_prefab(name, recipe, materials):
    """Fabricate a fresh consistent assembly from write_recipe JSON data.

    Caller explicitly supplies reusable Blender material-role bindings, allowing
    the same design/mechanism to be fabricated in wood, metal or custom finishes.
    Existing root/mesh names and sampled poses in the receipt are not reused.
    """
    if recipe.get('schema')!=1:
        raise ValueError('Unsupported opening prefab recipe')
    params=dict(recipe['parameters']);kind=params.pop('kind')
    if kind=='facade_details':
        from .CityBuildingFacadeDetails import create_facade_details_prefab
        params['facade']=Facade(**params['facade'])
        return create_facade_details_prefab(name,materials=materials,**params)
    if kind=='rooftop_element':
        from .CityBuildingRooftops import create_rooftop_element_prefab
        return create_rooftop_element_prefab(name,materials=materials,**params)
    if kind in ('pipe_route','pipe_socket'):
        from .CityBuildingPipes import create_pipe_route_prefab,create_pipe_socket_prefab
        constructor=create_pipe_route_prefab if kind=='pipe_route' else create_pipe_socket_prefab
        return constructor(name,materials=materials,**params)
    if kind in ('canopy','building_trim'):
        from .CityBuildingDetailPrefabs import create_canopy_prefab,create_building_trim_prefab
        constructor=create_canopy_prefab if kind=='canopy' else create_building_trim_prefab
        if 'facade' in params:params['facade']=Facade(**params['facade'])
        return constructor(name,materials=materials,**params)
    if kind not in ('door','window','garage'):raise ValueError('Unknown opening prefab kind')
    opening=Opening(**params.pop('opening'));facade=Facade(**params.pop('facade'))
    depth=params.pop('wall_depth')
    if kind=='garage':
        from .CityGaragePrefabs import create_garage_prefab
        constructor=create_garage_prefab
    else:constructor=create_door_prefab if kind=='door' else create_window_prefab
    return constructor(name,opening,depth,materials,facade=facade,**params)


def _motion(facade, bounds, depth, mode, side, angle, offset=(0,0,0), travel=(0,0,0)):
    x0,z0,x1,z1=bounds
    point = ((x0 if side=='left' else x1),z0,depth) if mode!='awning' else ((x0+x1)/2,z1,depth)
    pivot=Vector(facade.point(*point))+Vector(offset)
    axis=facade.right if mode=='awning' else facade.up
    sign=-1 if side=='left' or mode=='awning' else 1
    return dict(pivot=list(pivot),axis=list(axis),angle=sign*angle if mode in ('swing','awning') else 0.,
                travel=list(travel),closed_offset=list(offset),mode=mode)


def _material_check(materials):
    if set(materials)!=set(ROLES) or any(not isinstance(materials[r],bpy.types.Material) for r in ROLES):
        raise ValueError('Provide frame/leaf/panel/glass/hardware Blender material bindings')


def add_assembly_helpers(prefab, anchors):
    """Add named non-rendering attachment frames to a freshly built prefab.

    anchors maps semantic names to root-local Facade frames (X=right, Y=inward,
    Z=up). Parenting keeps them with assembly copies/moves. Matching JSON metadata
    survives mesh-only handoffs; helper empties are not required in runtime FBXs.
    This call creates only new children and rejects duplicate anchor names.
    """
    if any(not isinstance(f,Facade) for f in anchors.values()):raise ValueError('Expected attachment Facade frames')
    saved=prefab.recipe.setdefault('anchors',{})
    if set(saved)&set(anchors):raise ValueError('Assembly anchor already exists')
    collection=prefab.root.users_collection[0]
    for label,frame in anchors.items():
        helper=bpy.data.objects.new(prefab.root.name+'_'+label,None);collection.objects.link(helper)
        helper.parent=prefab.root;helper.location=frame.origin
        helper.rotation_euler=Matrix((frame.right,tuple(-x for x in frame.outward),frame.up)).transposed().to_euler()
        helper.empty_display_type='ARROWS';helper.empty_display_size=.18;helper['CityAssemblyAnchor']=label
        saved[label]=dict(frame=frame.__dict__,object=helper.name)
    prefab.root['CityOpeningRecipe']=json.dumps(prefab.recipe)
    bpy.context.view_layer.update()


def find_assembly_anchor(root, label):
    """Resolve a copied/renamed helper by semantic role; use its matrix_world."""
    matches=[o for o in root.children if o.get('CityAssemblyAnchor')==label]
    if len(matches)!=1:raise ValueError('Expected exactly one assembly anchor: '+label)
    return matches[0]


def _finish(name, geometry, static, moving, materials, parameters, hardware=None):
    if name in bpy.data.collections or name in bpy.data.objects:
        raise ValueError('Prefab name already exists; select a fresh name')
    _material_check(materials)
    assigned=static+[i for part in moving for i in part['faces']]
    if sorted(assigned)!=list(range(len(geometry.faces))):
        raise ValueError('Every generated face must belong to exactly one stationary/moving part')
    collection=bpy.data.collections.new(name);bpy.context.scene.collection.children.link(collection)
    root=bpy.data.objects.new(name,None);collection.objects.link(root)
    parts=[]
    def make(label,indices,pivot,offset):
        verts=[];faces=[]
        for i in indices:
            start=len(verts);verts.extend([Vector(p)+Vector(offset)-Vector(pivot) for p in geometry.faces[i]])
            faces.append(tuple(range(start,len(verts))))
        mesh=bpy.data.meshes.new(name+'_'+label);mesh.from_pydata(verts,[],faces)
        for role in ROLES:mesh.materials.append(materials[role])
        mask=mesh.color_attributes.new(name='WindowMask',type='BYTE_COLOR',domain='CORNER')
        uv=mesh.uv_layers.new(name='UVMap')
        for polygon,i in zip(mesh.polygons,indices):
            polygon.material_index=geometry.slots[i]
            for li,xy in zip(polygon.loop_indices,geometry.uvs[i]):
                mask.data[li].color=geometry.colors[i];uv.data[li].uv=xy
        obj=bpy.data.objects.new(name+'_'+label,mesh);collection.objects.link(obj);obj.parent=root
        obj.location=pivot;return obj
    make('Frame',static,(0,0,0),(0,0,0))
    for i,part in enumerate(moving):
        obj=make(f'Leaf{i+1}',part['faces'],part['pivot'],part['closed_offset']);parts.append(obj)
        obj['CityOpeningPart']=i
        part['object']=obj.name
        lookup={face:j for j,face in enumerate(part['faces'])}
        part['roles']={key:[lookup[f] for f in group] for key,group in part.pop('face_roles',{}).items()}
    recipe=dict(schema=1,units='meters/radians',parameters=parameters,parts=moving,
                materials={r:dict(name=materials[r].name,type=materials[r].get('CityOpeningMaterialType','custom')) for r in ROLES},
                hardware=hardware or {},root=root.name,stationary=name+'_Frame',limits='Root-local source motion; reserve swept/parking space in the building. No native collision/gameplay binding.')
    root['CityOpeningRecipe']=json.dumps(recipe);prefab=OpeningPrefab(root,parts,recipe);prefab.set_open(0)
    # Analytic extrema of each coordinate over the selected arc, not just poses.
    points=[v.co.copy() for obj in collection.objects if obj.type=='MESH' and 'CityOpeningPart' not in obj for v in obj.data.vertices]
    for obj,part in zip(parts,moving):
        axis=Vector(part['axis']);pivot=Vector(part['pivot']);travel=Vector(part['travel']);angle=part['angle']
        for vertex in obj.data.vertices:
            v=vertex.co;axial=axis*v.dot(axis);perp=v-axial;cross=axis.cross(v)
            if part['mode']=='sectional':
                spec=part['sectional'];inward,z,_=sectional_pose(amount=1.,**spec)
                closed=(spec['index']+.5)*spec['height']/spec.get('count',24)
                extent=Vector([math.hypot(perp[k],cross[k]) for k in range(3)])
                # Conservative continuous envelope: monotone track-center rectangle
                # plus full rotating cross-section extents. Does not depend on samples.
                for dz in (0,z-closed):
                    for d in (0,inward):
                        center=pivot+Vector(part['track_up'])*dz-Vector(part['track_outward'])*d+axial
                        points.extend([center-extent,center+extent])
                continue
            if angle==0:
                points.extend([pivot+v,pivot+v+travel]);continue
            for k in range(3):
                phase=math.atan2(cross[k],perp[k])
                candidates=[0,angle]+[phase+j*math.pi for j in range(-2,3) if min(0,angle)<=phase+j*math.pi<=max(0,angle)]
                for a in candidates:
                    points.append(pivot+axial+perp*math.cos(a)+cross*math.sin(a))
    recipe['motion_bounds_m']=[[min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)]]
    prefab.set_open(0);root['CityOpeningRecipe']=json.dumps(recipe)
    params=parameters
    if 'opening' in params:
        o=Opening(**params['opening']);f=Facade(**params['facade']);x,z,x1,z1=o.bounds
        add_assembly_helpers(prefab,{name:Facade(f.point(a,b,0),f.right,f.up) for name,a,b in
            [('Mount',0,0),('OpeningLowerLeft',x,z),('OpeningLowerRight',x1,z),
             ('OpeningUpperLeft',x,z1),('OpeningUpperRight',x1,z1),('OpeningCenter',(x+x1)/2,(z+z1)/2)]})
    return prefab


def create_door_prefab(name, opening, wall_depth, materials, *, facade=Facade(), design='panelled',
                       motion='swing', leaves=1, hinge='left', angle_degrees=90., handles=True):
    """Create door prefab: outward swing or exterior surface-mounted slide.

    design accepts flush, panelled, six_panel, half_glazed, arched_glazed or
    full_glazed; see CityBuildingEntrances.DOOR_DESIGNS. 'glazed' is invalid,
    and this wrapper does not accept the low-level glazed boolean.
    name must be fresh in both bpy.data.objects and bpy.data.collections;
    deleting old objects alone may leave their collection name reserved.

    Two swing leaves hinge on opposite jambs; two slides part in opposite
    directions. Sliding leaves park outside the aperture, clear of the wall;
    a guide rail and motion envelope identify the required adjacent wall space.
    Wood/metal/glass mixes use independently bound leaf/panel/glass roles.
    Set handles=False for automatic doors; guide/saddle hardware remains attached.
    """
    if motion not in ('fixed','swing','slide') or hinge not in ('left','right'):
        raise ValueError('Door motion is fixed/swing/slide; hinge is left/right')
    if not isinstance(angle_degrees,(int,float)) or not math.isfinite(angle_degrees) or not 0 < angle_degrees <= 100:
        raise ValueError('Door swing angle must be in (0,100]')
    if type(handles) is not bool:
        raise ValueError('Door handles must be a boolean')
    _material_check(materials)
    b=_Geometry();record=create_door(b,opening,wall_depth,facade=facade,leaves=leaves,design=design,
                                   frame_slot=0,leaf_slot=1,panel_slot=2,glass_slot=3)
    static=_indices(record['roles']);moving=[];hardware={}
    for i,leaf in enumerate(record['leaves']):
        side=('left' if i==0 else 'right') if leaves==2 else hinge
        x0,z0,x1,z1=leaf['bounds'];margin=min(.10,(x1-x0)*.2)
        handle_x=x1-margin if side=='left' else x0+margin
        half_width=min(.012,(x1-x0)*.04)
        ids=_indices(leaf['roles'])
        low,high=(.36,.42) if design in ('half_glazed','arched_glazed') else (.44,.52)
        handle_roles={}
        if handles:
            handle_roles['handle_plate']=_box(b,facade,(handle_x-half_width*2,z0+(z1-z0)*(low-.012),handle_x+half_width*2,z0+(z1-z0)*(high+.012)),.012,-.006,4)
            handle_roles['handle_grip']=_box(b,facade,(handle_x-half_width,z0+(z1-z0)*low,handle_x+half_width,z0+(z1-z0)*high),.055,.008,4)
            ids+=_indices(handle_roles)
        if motion=='slide':
            # Simple saddle hangers wrap over the guide; no wheel simulation.
            rail_bottom=opening.z+opening.height+.005;rail_top=rail_bottom+.04
            hangers=[]
            for fraction in (.2,.8):
                x=x0+(x1-x0)*fraction;w=min(.014,(x1-x0)*.035)
                # Geometry is pre-offset: the leaf's closed slide offset adds65mm.
                hangers+=_box(b,facade,(x-w*1.6,z1-.055,x+w*1.6,z1-.015),.108-.065,.053-.065,4)
                hangers+=_box(b,facade,(x-w,z1-.04,x+w,rail_top+.016),.108-.065,.096-.065,4)
                hangers+=_box(b,facade,(x-w,rail_top+.004,x+w,rail_top+.016),.108-.065,.023-.065,4)
                hangers+=_box(b,facade,(x-w,rail_bottom+.005,x+w,rail_top+.016),.035-.065,.023-.065,4)
            handle_roles['hangers']=hangers;ids+=hangers
        offset=Vector(facade.outward)*(.065 if motion=='slide' else 0)
        travel=Vector(facade.right)*((x1-x0+.004)*(-1 if side=='left' else 1) if motion=='slide' else 0)
        moving.append(dict(faces=ids,face_roles=dict(**leaf['roles'],**handle_roles),**_motion(facade,leaf['bounds'],0,motion,side,math.radians(angle_degrees),offset,travel)))
    if motion=='slide':
        x0,z0,x1,z1=opening.bounds
        # Full conservative guide length in facade units, including both parking regions.
        span=opening.width if leaves==1 else opening.width/2
        static+=_box(b,facade,(x0-span,z1+.005,x1+span,z1+.045),.09,.04,4)
        hardware=dict(type='hanging_guide_with_two_saddle_hangers_per_leaf',rail_z=[z1+.005,z1+.045],
                      rail_depth=[.04,.09],saddle_top_gap_m=.004,front_gap_m=.006,rear_gap_m=.005)
    return _finish(name,b,static,moving,materials,dict(kind='door',opening=opening.__dict__,wall_depth=wall_depth,
                   facade=facade.__dict__,design=design,motion=motion,leaves=leaves,hinge=hinge,angle_degrees=angle_degrees,handles=handles),hardware)


def create_window_prefab(name, opening, wall_depth, materials, *, facade=Facade(), motion='swing',
                         leaves=1, hinge='left', columns=1, rows=1, angle_degrees=None):
    """Create fixed/casement/top-hung awning or two-track bypass window.

    Sliding windows use two leaves; the left slides over the stationary right
    sash on a separate track, giving about half-width ventilation. Awning is a
    single top-hinged sash. Mullions/glass move with their sash, never the jamb.
    """
    if motion not in ('fixed','swing','awning','slide') or hinge not in ('left','right'):
        raise ValueError('Window motion is fixed/swing/awning/slide; hinge left/right')
    if type(leaves) is not int or leaves not in (1,2) or (motion=='awning' and leaves!=1) or (motion=='slide' and leaves!=2):
        raise ValueError('Window needs one/two leaves; awning one and sliding two')
    angle_degrees=(45 if motion=='awning' else 90) if angle_degrees is None else angle_degrees
    limit=60 if motion=='awning' else 100
    if not isinstance(angle_degrees,(int,float)) or not math.isfinite(angle_degrees) or not 0 < angle_degrees <= limit:
        raise ValueError('Window angle exceeds its selected mechanism limit')
    _material_check(materials);_fit(opening,facade,wall_depth,.075,.02)
    b=_Geometry();x0,z0,x1,z1=opening.bounds;gap=.004
    sw=(opening.width-.15-gap*(leaves+1))/leaves;sh=opening.height-.15-2*gap
    # Sash construction is validated before Blender objects are created.
    sash_records=[]
    for i in range(leaves):
        o=Opening(x0+.075+gap+i*(sw+gap),z0+.075+gap,sw,sh)
        rec=create_window(b,o,.04,facade=facade,frame_width=.045,frame_proud=0.,glass_recess=.016,
                          glass_thickness=.004,overlap=.008,columns=columns,rows=rows,frame_slot=1,glass_slot=3)
        sash_records.append((o,rec))
    static=_indices(_frame(b,facade,opening.bounds,.075,.02,-wall_depth,0));moving=[];hardware={}
    for i,(o,rec) in enumerate(sash_records):
        side=('left' if i==0 else 'right') if leaves==2 else hinge
        mode='fixed' if motion=='slide' and i==1 else motion
        offset=Vector(facade.outward)*(.05 if motion=='slide' and i==0 else 0)
        travel=Vector(facade.right)*(sw+gap if motion=='slide' and i==0 else 0)
        moving.append(dict(faces=_indices(rec['roles']),face_roles=rec['roles'],**_motion(facade,o.bounds,0,mode,side,math.radians(angle_degrees),offset,travel)))
    if motion=='slide':
        # Retaining lips overlap the sash cap vertically while separate depth
        # tracks leave clearance around both moving and stationary sashes.
        for low,high,base_low,base_high in ((z0+.05,z0+.10,z0+.05,z0+.065),
                                          (z1-.10,z1-.05,z1-.065,z1-.05)):
            static+=_box(b,facade,(x0+.075,base_low,x1-.075,base_high),.065,-.055,4)
            for back,front in ((-.055,-.045),(.002,.008),(.055,.065)):
                static+=_box(b,facade,(x0+.075,low,x1-.075,high),front,back,4)
        hardware=dict(type='two_track_retaining_channels',lip_depths=[[-.055,-.045],[.002,.008],[.055,.065]],
                      lower_lip_z=[z0+.05,z0+.10],upper_lip_z=[z1-.10,z1-.05],sash_cap_capture_m=.021,
                      minimum_depth_gap_m=.002)
    return _finish(name,b,static,moving,materials,dict(kind='window',opening=opening.__dict__,wall_depth=wall_depth,
                   facade=facade.__dict__,motion=motion,leaves=leaves,hinge=hinge,columns=columns,rows=rows,angle_degrees=angle_degrees),hardware)
