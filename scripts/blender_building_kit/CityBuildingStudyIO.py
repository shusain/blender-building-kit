"""Small Blender study helpers; canonical FBX labels and actual readback."""
import bpy,hashlib
from pathlib import Path
from contextlib import contextmanager

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_object(source,name):
    """Append an independent mesh from a blend, link it and reset its location.

    Copies the mesh data so study edits do not modify the source datablock."""
    with bpy.data.libraries.load(str(source),link=False) as (available,loaded):
        assert name in available.objects;loaded.objects=[name]
    obj=loaded.objects[0];bpy.context.scene.collection.objects.link(obj);obj.data=obj.data.copy();obj.location=(0,0,0);obj.hide_set(False);obj.hide_render=False
    return obj

class Materials:
    """Cache appended source materials by blend path and canonical material name.

    load() appends on demand; restore() replaces an object's material slots with
    those source materials. Neither method saves a blend or exports an FBX."""
    def __init__(self):self.cache={}
    def load(self,source,name):
        key=(str(source),name)
        if key not in self.cache:
            with bpy.data.libraries.load(str(source),link=False) as (available,loaded):
                choices=[n for n in available.materials if n.split('.')[0]==name];assert choices,(source,name);loaded.materials=[name if name in choices else choices[0]]
            m=loaded.materials[0];m.use_nodes=True
            if len(m.node_tree.nodes)==2:
                p=m.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=m.diffuse_color;p.inputs['Roughness'].default_value=.7
            self.cache[key]=m
        return self.cache[key]
    def restore(self,obj,source):
        names=[m.name.split('.')[0] for m in obj.data.materials]
        for i,name in enumerate(names):obj.data.materials[i]=self.load(source,name)
        return names

def _temporary_prefix(prefix,extra=()):
    names=[m.name for m in bpy.data.materials]+list(extra)
    while any(name.startswith(prefix) for name in names):prefix='_'+prefix
    return prefix


def _restore_names(saved):
    prefix=_temporary_prefix('_StudyRestore_', [name for m,name in saved])
    for i,(material,name) in enumerate(saved):
        material.name=prefix+str(i)
    for material,name in saved:
        material.name=name


def _export_study(obj,path,slots):
    saved=[(m,m.name) for m in bpy.data.materials] if slots is not None else []
    try:
        if slots is not None:
            if len(slots)!=len(obj.data.materials):
                raise ValueError('Canonical labels must match the mesh material slots')
            prefix=_temporary_prefix('_D91Export_', slots)
            for i,(m,name) in enumerate(saved):m.name=prefix+str(i)
            for m,name in zip(obj.data.materials,slots):m.name=name
        bpy.ops.object.select_all(action='DESELECT');obj.select_set(True)
        bpy.context.view_layer.objects.active=obj
        bpy.ops.export_scene.fbx(filepath=str(path),use_selection=True,object_types={'MESH'},
            apply_unit_scale=True,global_scale=1,axis_forward='-Y',axis_up='Z',bake_anim=False,
            add_leaf_bones=False,path_mode='STRIP',mesh_smooth_type='FACE')
    finally:
        if saved:_restore_names(saved)


@contextmanager
def checked_fbx(obj,path,slots=None,*,dimension_tolerance=.002,expected_triangles=None,expected_sections=None,verify_alpha=False):
    """Static study export/readback transaction; yield the actual imported mesh.

    Optional canonical labels isolate duplicate semantic material names. Each
    study retains its own pane/geometry checks inside the context. On any exit,
    restore source labels/selection and remove imported objects/unused data.
    """
    bpy.context.view_layer.update();obj.data.calc_loop_triangles()
    triangles=len(obj.data.loop_triangles) if expected_triangles is None else expected_triangles
    sections=len(obj.data.materials) if expected_sections is None else expected_sections
    selected=list(bpy.context.selected_objects);active=bpy.context.view_layer.objects.active
    original_objects=set(bpy.data.objects);original_meshes=set(bpy.data.meshes);original_materials=set(bpy.data.materials)
    original_images=set(bpy.data.images)
    try:
        _export_study(obj,path,slots)
        bpy.ops.import_scene.fbx(filepath=str(path))
        meshes=[o for o in set(bpy.data.objects)-original_objects if o.type=='MESH']
        assert len(meshes)==1,('Expected one FBX mesh',str(path),len(meshes))
        check=meshes[0];check.data.calc_loop_triangles()
        assert len(check.data.loop_triangles)==triangles and len(check.data.materials)==sections,(str(path),triangles,sections)
        assert all(abs(a-b)<dimension_tolerance for a,b in zip(check.dimensions,obj.dimensions)),('FBX dimensions',str(path))
        if slots is not None:
            assert [m.name.split('.')[0] for m in check.data.materials]==list(slots),(str(path),[m.name for m in check.data.materials],slots)
        attr=obj.data.color_attributes.get('WindowMask')
        if verify_alpha and attr:
            check_attr=check.data.color_attributes.get('WindowMask')
            assert check_attr and [v.color[3] for v in attr.data]==[v.color[3] for v in check_attr.data]
        yield check
    finally:
        for other in set(bpy.data.objects)-original_objects:bpy.data.objects.remove(other,do_unlink=True)
        for mesh in set(bpy.data.meshes)-original_meshes:
            if mesh.users==0:bpy.data.meshes.remove(mesh)
        for material in set(bpy.data.materials)-original_materials:
            if material.users==0:bpy.data.materials.remove(material)
        for image in set(bpy.data.images)-original_images:
            if image.users==0:bpy.data.images.remove(image)
        bpy.ops.object.select_all(action='DESELECT')
        for other in selected:
            if other.name in bpy.context.view_layer.objects:other.select_set(True)
        if active and active.name in bpy.context.view_layer.objects:bpy.context.view_layer.objects.active=active


def window_faces(obj,materials=None):
    """Count panes with the existing all-corner alpha threshold and optional slots."""
    attr=obj.data.color_attributes['WindowMask']
    return sum((materials is None or obj.data.materials[p.material_index].name.split('.')[0] in materials)
               and all(attr.data[i].color[3]<.01 for i in p.loop_indices) for p in obj.data.polygons)


def export_checked(obj,path,slots):
    with checked_fbx(obj,path,slots,verify_alpha=True):pass
    return dict(sha256=digest(path),triangles=len(obj.data.loop_triangles),sections=len(slots),dimensions_m=list(obj.dimensions),roundtrip_pass=True)


def snapshot(obj):
    mesh=obj.data;attr=mesh.color_attributes.get('WindowMask');uv=mesh.uv_layers.active
    return dict(vertices=[tuple(v.co) for v in mesh.vertices],faces=[tuple(p.vertices) for p in mesh.polygons],slots=[p.material_index for p in mesh.polygons],uv=[tuple(v.uv) for v in uv.data] if uv else None,rgba=[tuple(v.color) for v in attr.data] if attr else None)
