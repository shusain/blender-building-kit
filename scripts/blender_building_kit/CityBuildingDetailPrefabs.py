"""Editable Blender trim/canopy assemblies using the shared prefab lifecycle.

Creates fresh current-scene collections, meshes and non-rendering attachment
helpers. Stores portable parameters/placement metadata on the root; explicit
write_recipe exports JSON and fabricate_prefab rebuilds it. No file saves,
production edits, native import or deletion of caller-owned assemblies.
"""
from dataclasses import asdict

from .CityBuildingEntrances import Facade,Opening
from .CityBuildingDetails import create_canopy,create_building_trim
from .CityBuildingOpeningPrefabs import _Geometry,_finish,add_assembly_helpers


def create_canopy_prefab(name,width,projection,materials,*,facade=Facade(),style='sloped',rise=.45,
                         drop=.3,thickness=.06,supports='brackets',support_height=2.4,stripes=6,
                         protected_openings=(),opening_facade=None,opening_clearance=.025):
    """Create editable canopy with rear mount, front span and support contacts.

    facade.origin is the rear roof/eave level, not ground or door origin.
    Set its height explicitly and check fascia/support clearance below it.
    name must be fresh in both object and collection data, including replacements.
    Slots bind roof=leaf, fascia=frame, support=panel, stripe=hardware; glass is
    unused. These semantic bindings reuse the existing five-role material API.
    Optional protected door/window openings and their frame persist in the
    recipe. A clearance failure occurs before any scene objects are created.
    """
    b=_Geometry();params=dict(width=width,projection=projection,facade=facade,style=style,rise=rise,
                              drop=drop,thickness=thickness,supports=supports,support_height=support_height,stripes=stripes)
    protected_openings=tuple(protected_openings)
    if isinstance(opening_facade, dict):
        opening_facade=Facade(**opening_facade)
    report=create_canopy(b,**params,roof_slot=1,edge_slot=0,support_slot=2,accent_slot=4,
                         protected_openings=protected_openings,opening_facade=opening_facade,
                         opening_clearance=opening_clearance)
    params['facade']=facade.__dict__
    if protected_openings:
        params['protected_openings']=[asdict(o) if isinstance(o,Opening) else dict(o) for o in protected_openings]
        if opening_facade is not None:
            params['opening_facade']=asdict(opening_facade)
        params['opening_clearance']=opening_clearance
    prefab=_finish(name,b,list(range(len(b.faces))),[],materials,dict(kind='canopy',**params),report)
    anchors={key:Facade(facade.point(x,0,d),facade.right,facade.up) for key,x,d in
             [('Mount',0,0),('RearRight',width,0),('FrontLeft',0,projection),('FrontRight',width,projection)]}
    # Front helpers denote projection footprint at mounting datum; contact helpers
    # carry actual roof-profile height. Both meanings are explicit in the recipe.
    for i,point in enumerate(report['support_contacts']):anchors['SupportContact_'+str(i)]=Facade(point,facade.right,facade.up)
    add_assembly_helpers(prefab,anchors);return prefab


def create_building_trim_prefab(name,width,depth,floors,materials,floor_height=3.,**options):
    """Create replaceable trim branch with envelope/floor/facade attachment frames.

    Re-fabricate new parameters, swap only the caller-owned trim branch, and keep
    other meshes/parts. Plan bands expose exact face IDs for selective finishes.
    """
    b=_Geometry();plan=create_building_trim(b,width,depth,floors,floor_height,**options)
    if not b.faces:raise ValueError('Trim prefab needs at least one enabled band')
    prefab=_finish(name,b,list(range(len(b.faces))),[],materials,dict(kind='building_trim',**plan['parameters']),plan)
    anchors={key:Facade(**row['frame']) for key,row in plan['facades'].items()}
    origin=plan['datums']['origin'];right=plan['datums']['right']
    anchors['Mount']=Facade(origin,right,(0,0,1))
    for n,z in enumerate(plan['datums']['floor_levels_m']):
        anchors['Floor_'+str(n)]=Facade((origin[0],origin[1],origin[2]+z),right,(0,0,1))
    anchors['WallTop']=Facade((origin[0],origin[1],origin[2]+plan['assembly_seats']['wall_top_m']),right,(0,0,1))
    add_assembly_helpers(prefab,anchors);return prefab
