"""Portable sectional-garage path extracted from accepted #591 source poses.

Ordinary Python, meters/radians; no Blender, files or native writes. Defaults
match CityStationGarage::Panel and the six approved station handoffs. Native
production remains unchanged; this is the reusable source-authoring contract.
"""
import math


def garage_closure(width,height,wall_depth,inset,*,count=24,radius=.65,side_overlap=.015,clearance=.004):
    """Derive side coverage/return depth without reducing clear bay width.

    Panels overlap BEHIND the jambs instead of leaving a15mm side slit. The
    jamb returns stop in front of the continuous moving-panel envelope, with
    explicit clearance. Dimensions are meters; no Blender or scene/file writes.
    Existing station pose equations and production meshes are unchanged.
    """
    sectional_pose(height,0,0,count=count,radius=radius)
    if any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in (width,wall_depth,inset,side_overlap,clearance)):
        raise ValueError('Garage closure dimensions must be finite and positive')
    panel_height=height/count-.012
    if panel_height<=0:raise ValueError('Garage panel pitch leaves no positive panel height')
    # Continuous minimum inward coordinate over the quarter bend, including
    # rotating thickness/half-height, not just the panel-center path.
    front_reach=math.hypot(radius+.0175,panel_height/2)-radius
    # Keep the return back plane beyond the host's inner wall plane as well as
    # clear of the moving leaf, including at the minimum supported inset.
    minimum_inset=wall_depth+front_reach+2*clearance
    track_gap=.045-.018-side_overlap
    if inset+1e-9<minimum_inset:raise ValueError('Panel inset must clear wall and closing jamb returns')
    if track_gap+1e-9<clearance:raise ValueError('Side overlap consumes garage track clearance')
    minimum_overlap=front_reach-.0175+clearance
    if side_overlap+1e-9<minimum_overlap:
        raise ValueError(f'Side overlap must be at least {minimum_overlap:.6f}m to cover closing-return clearance at oblique views')
    return dict(panel_width_m=width+2*side_overlap,panel_height_m=panel_height,
                closed_side_overlap_m=side_overlap,frame_back_depth_m=-inset+front_reach+clearance,
                minimum_inset_m=minimum_inset,moving_front_clearance_m=clearance,track_side_clearance_m=track_gap)


def sectional_pose(height, index, amount, *, count=24, radius=.65, headroom=.1, extra_travel=1.):
    """Return inward travel, height and negative hinge angle of one panel.

    Path is vertical, quarter-circle then horizontal overhead. Panel index0 is
    bottommost when closed. All dimensional/state checks precede computation.
    """
    if type(count) is not int or count<2 or type(index) is not int or not 0<=index<count:
        raise ValueError('Sectional count/index must select a valid panel')
    if any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in (height,amount,radius,headroom,extra_travel)):
        raise ValueError('Sectional path inputs must be finite')
    if height<=0 or radius<=0 or headroom<0 or extra_travel<0 or not 0<=amount<=1:
        raise ValueError('Invalid sectional dimensions/openness')
    start=height+headroom;arc=radius*math.pi/2
    q=(index+.5)*height/count+(height+extra_travel)*amount-start
    if q<=0:return (0.,q+start,0.)
    if q<arc:
        angle=q/radius
        return (radius*(1-math.cos(angle)),start+radius*math.sin(angle),-angle)
    return (radius+q-arc,start+radius,-math.pi/2)
