"""Blender sectional garage fabrication from shared frame/track and panel data.

read_garage_panel explicitly reads a hash-pinned source component, returns a
portable mesh profile and removes its temporary datablocks. create_garage_prefab
only writes a fresh current-scene collection/root/parts, reusing the existing
opening prefab lifecycle/pose/recipe API. No files or native content are saved.
Defaults preserve the accepted #591 24-panel path; callers own building fit and
source review. Closed panels sit480mm inward from the facade, as on the stations.
"""
import math
from pathlib import Path
import bpy
from .CityBuildingEntrances import Facade, _box, _prism, _positive, _face
from .CityBuildingOpeningPrefabs import _Geometry, _finish, _material_check
from .CityBuildingStudyIO import load_object, digest
from .CityGarageGeometry import sectional_pose,garage_closure


def read_garage_panel(source, sha256, object_name):
    """Extract a pinned centered panel into JSON-safe geometry, UV and provenance.

    Does not save the input. This explicit source operation retains corner UVs
    and uniform per-face color, and rejects uncentered/multi-material profiles.
    The returned profile is embedded in fabrication recipes; later copies do
    not need the original blend on disk.
    """
    source=Path(source).resolve()
    if digest(source)!=sha256:raise ValueError('Garage source hash mismatch')
    before=[set(bpy.data.objects),set(bpy.data.meshes),set(bpy.data.materials),set(bpy.data.images)]
    try:
        obj=load_object(source,object_name);mesh=obj.data
        coords=[tuple(v.co) for v in mesh.vertices]
        low=[min(p[k] for p in coords) for k in range(3)];high=[max(p[k] for p in coords) for k in range(3)]
        if any(abs(a+b)>1e-5 or b-a<=0 for a,b in zip(low,high)):
            raise ValueError('Garage template must be centered and have positive thickness')
        if len({p.material_index for p in mesh.polygons})!=1 or mesh.uv_layers.active is None:
            raise ValueError('Garage template needs one semantic panel material and UVs')
        attr=mesh.color_attributes.get('WindowMask');colors=[]
        for face in mesh.polygons:
            row=[tuple(attr.data[i].color) for i in face.loop_indices] if attr else [(1,1,1,1)]
            if any(c!=row[0] for c in row):raise ValueError('Panel profile requires uniform face colors')
            colors.append(row[0])
        result=dict(source=source.name,sha256=sha256,object=object_name,vertices=coords,
                    faces=[list(p.vertices) for p in mesh.polygons],colors=colors,
                    uv=[[list(mesh.uv_layers.active.data[i].uv) for i in p.loop_indices] for p in mesh.polygons],
                    dimensions=[b-a for a,b in zip(low,high)])
        if digest(source)!=sha256:raise ValueError('Garage source changed during extraction')
        return result
    finally:
        for obj in set(bpy.data.objects)-before[0]:bpy.data.objects.remove(obj,do_unlink=True)
        for blocks,old in zip((bpy.data.meshes,bpy.data.materials,bpy.data.images),before[1:]):
            for block in set(blocks)-old:
                if block.users==0:blocks.remove(block)


def create_garage_prefab(name, opening, wall_depth, materials, *, facade=Facade(), panel_count=24,
                         radius=.65, inset=.48, headroom=.1, extra_travel=1., panel_template=None,
                         side_overlap=.015, frame_clearance=.004, frame_width=.12, header_height=.15):
    """Build jamb/header, two overhead guide tracks and centered movable panels.

    Opening denotes clear bay size; frame is OUTSIDE it to preserve vehicle
    clearance. Defaults use the accepted station12-triangle panel profile,
    width+30mm (15mm overlap behind each jamb), height/count-12mm and35mm thickness.
    Deep jamb returns close the side sightline while clearing the full panel
    sweep by frame_clearance. Optional extracted template
    is scaled to those dimensions with its original corner UVs. No station
    building shell, bay reservations or native gameplay is changed.
    The matching host wall supplies its aperture reveal through wall_depth;
    frame return faces omit that region to avoid exposed coplanar skins.
    frame_width/header_height size the facade surround from the same clear
    aperture as the curtain. Bind the frame role to the desired facade finish
    instead of retaining a separately sized legacy surround.
    """
    _material_check(materials)
    for value,label in ((wall_depth,'wall depth'),(inset,'panel inset'),
                        (frame_width,'frame width'),(header_height,'header height')):_positive(value,label)
    sectional_pose(opening.height,0,0,count=panel_count,radius=radius,headroom=headroom,extra_travel=extra_travel)
    if not isinstance(facade,Facade) or opening.width<=.06 or opening.height/panel_count<=.024:
        raise ValueError('Garage opening/panel count leaves no positive panel geometry')
    if extra_travel<radius*math.pi/2-radius or radius<opening.height/panel_count:
        raise ValueError('Track travel/radius is insufficient for the selected sectional panels')
    closure=garage_closure(opening.width,opening.height,wall_depth,inset,count=panel_count,radius=radius,
                          side_overlap=side_overlap,clearance=frame_clearance)
    x0,z0,x1,z1=opening.bounds;b=_Geometry();static=[];moving=[]
    stop=closure['frame_back_depth_m']
    for kind,rect in (('left',(x0-frame_width,z0,x0,z1)),('right',(x1,z0,x1+frame_width,z1)),
                      ('top',(x0-frame_width,z1,x1+frame_width,z1+header_height))):
        # Host wall owns the aperture reveal through0..wall_depth. Keep only
        # front/deep return faces there, avoiding a second exposed coplanar skin.
        box=_Geometry();_box(box,Facade(),rect,.03,stop,0)
        axis,edge=(2,z1) if kind=='top' else (0,x0 if kind=='left' else x1)
        for points,color,uv in zip(box.faces,box.colors,box.uvs):
            if all(p[axis]==edge for p in points):continue
            b.face([facade.point(p[0],p[2],-p[1]) for p in points],0,color,uv)
        for front,back in ((.03,0),(-wall_depth,stop)):
            if kind=='top':points=[(rect[0],z1,back),(rect[2],z1,back),(rect[2],z1,front),(rect[0],z1,front)]
            else:
                points=[(edge,z0,back),(edge,z1,back),(edge,z1,front),(edge,z0,front)]
                if kind=='right':points.reverse()
            _face(b,facade,points,0)
    static=list(range(len(b.faces)))
    # Local track points in z/outward-depth. Profiles are thin rectangular beams,
    # with an eight-segment bend and continuous matching endpoints.
    start=opening.height+headroom
    end_inward,end_z,_=sectional_pose(opening.height,panel_count-1,1,count=panel_count,radius=radius,headroom=headroom,extra_travel=extra_travel)
    points=[(z0,-inset),(z0+start,-inset)]
    points += [(z0+start+radius*math.sin(j*math.pi/16),-inset-radius*(1-math.cos(j*math.pi/16))) for j in range(1,9)]
    points += [(z0+start+radius,-inset-end_inward-.15)]
    for x in (x0-.045,x1+.045):
        track=Facade(facade.point(x,0,0),facade.up,facade.outward)
        for a,c in zip(points,points[1:]):
            dz,dd=c[0]-a[0],c[1]-a[1];length=math.hypot(dz,dd)
            if length<1e-8:continue
            n=(-dd/length*.018,dz/length*.018)
            outline=[(a[0]+n[0],a[1]+n[1]),(a[0]-n[0],a[1]-n[1]),(c[0]-n[0],c[1]-n[1]),(c[0]+n[0],c[1]+n[1])]
            static+=_prism(b,track,outline,.018,-.018,4)
    width=closure['panel_width_m'];ph=closure['panel_height_m']
    for i in range(panel_count):
        center_z=z0+(i+.5)*opening.height/panel_count;center_x=(x0+x1)/2
        if panel_template is None:
            ids=_box(b,facade,(center_x-width/2,center_z-ph/2,center_x+width/2,center_z+ph/2),-inset+.0175,-inset-.0175,1)
        else:
            dims=panel_template['dimensions'];begin=len(b.faces)
            for face,uv,color in zip(panel_template['faces'],panel_template['uv'],panel_template['colors']):
                pts=[]
                for index in face:
                    x,y,z=panel_template['vertices'][index]
                    pts.append(facade.point(center_x+x*width/dims[0],center_z+z*ph/dims[2],-inset-y*.035/dims[1]))
                b.face(pts,1,color,uv)
            ids=list(range(begin,len(b.faces)))
        moving.append(dict(faces=ids,pivot=list(facade.point(center_x,center_z,-inset)),axis=list(facade.right),
                           angle=0.,travel=[0,0,0],closed_offset=[0,0,0],mode='sectional',track_up=list(facade.up),
                           track_outward=list(facade.outward),sectional=dict(height=opening.height,index=i,count=panel_count,
                           radius=radius,headroom=headroom,extra_travel=extra_travel)))
    prefab=_finish(name,b,static,moving,materials,dict(kind='garage',opening=opening.__dict__,wall_depth=wall_depth,
                   facade=facade.__dict__,panel_count=panel_count,radius=radius,inset=inset,headroom=headroom,
                   extra_travel=extra_travel,panel_template=panel_template,side_overlap=side_overlap,frame_clearance=frame_clearance,
                   frame_width=frame_width,header_height=header_height),
                   dict(type='sectional_overhead_tracks',clear_width_m=opening.width,clear_height_m=opening.height,
                        required_overhead_m=headroom+radius+.1,required_inside_depth_m=inset+end_inward+.15,
                        closure=closure,wall_throat_owner='host_wall',
                        wall_throat_depth_range_m=[-wall_depth,0]))
    # One reusable centered mesh, many independently posed panel objects, matching
    # the existing station native pool. Only fresh owned data is replaced here.
    shared=prefab.parts[0].data
    for obj in prefab.parts[1:]:
        old=obj.data;obj.data=shared
        if old.users==0:bpy.data.meshes.remove(old)
    return prefab
