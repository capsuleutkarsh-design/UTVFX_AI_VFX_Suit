import json
import os

def export_roto_to_nuke(json_path, out_nk_path, interp_mode="Linear"):
    with open(json_path, "r") as f:
        shapes = json.load(f)
        
    # Determine Nuke interpolation type string
    nuke_interp = "rp.AnimCurve.InterpolationType.LINEAR" if interp_mode == "Linear" else "rp.AnimCurve.InterpolationType.SMOOTH"
        
    shapes_data_str = json.dumps(shapes)
    
    # Create the Python script that Nuke will execute to build the roto node.
    py_script = f"""import json
import nuke
import nuke.rotopaint as rp
import random

shapes_data = json.loads(r'''{shapes_data_str}''')

def compute_tangents(pts):
    N = len(pts)
    left_tangents = []
    right_tangents = []
    import math
    for i in range(N):
        pt_type = pts[i][2] if len(pts[i]) > 2 else "smooth"
        if pt_type == "cusp":
            left_tangents.append((0.0, 0.0))
            right_tangents.append((0.0, 0.0))
        else:
            p_curr = pts[i]
            p_prev = pts[(i-1)%N]
            p_next = pts[(i+1)%N]
            
            d_prev = math.hypot(p_curr[0] - p_prev[0], p_curr[1] - p_prev[1])
            d_next = math.hypot(p_next[0] - p_curr[0], p_next[1] - p_curr[1])
            d_total = d_prev + d_next
            
            if d_total == 0:
                left_tangents.append((0.0, 0.0))
                right_tangents.append((0.0, 0.0))
            else:
                dir_x = (p_next[0] - p_prev[0]) / 3.0
                dir_y = (p_next[1] - p_prev[1]) / 3.0
                
                scale_left = d_prev / d_total
                scale_right = d_next / d_total
                
                left_tangents.append((dir_x * scale_left, dir_y * scale_left))
                right_tangents.append((dir_x * scale_right, dir_y * scale_right))
                
    return left_tangents, right_tangents

def generate_color(sid):
    random.seed(str(sid))
    r = random.uniform(0.2, 1.0)
    g = random.uniform(0.2, 1.0)
    b = random.uniform(0.2, 1.0)
    return (r, g, b)

def get_centroid_name(pts, format_width, format_height):
    if not pts: return "Center"
    avg_x = sum(pt[0] for pt in pts) / len(pts)
    avg_y = sum(pt[1] for pt in pts) / len(pts)
    
    x_pos = "Center"
    if avg_x < format_width * 0.33: x_pos = "Left"
    elif avg_x > format_width * 0.66: x_pos = "Right"
        
    y_pos = ""
    if avg_y < format_height * 0.33: y_pos = "Bottom"
    elif avg_y > format_height * 0.66: y_pos = "Top"
        
    if x_pos == "Center" and y_pos == "": return "Center"
    if y_pos == "": return x_pos
    if x_pos == "Center": return y_pos
    return f"{{y_pos}}{{x_pos}}"

frames = sorted([int(k) for k in shapes_data.keys() if str(k).isdigit()])
if not frames:
    nuke.message('No shape data found.')
else:
    format_w = shapes_data.get("format_width", 1920)
    format_h = shapes_data.get("format_height", 1080)

    roto_node = nuke.thisNode()
    roto_node['name'].setValue('UTVFX_AI_Roto')
    
    curves = roto_node['curves']
    root = curves.rootLayer
    
    # Create organizational layers
    shapes_layer = rp.Layer(curves)
    shapes_layer.name = 'Shapes'
    root.append(shapes_layer)
    
    holes_layer = rp.Layer(curves)
    holes_layer.name = 'Holes'
    root.append(holes_layer)
    
    nuke_shapes = {{}}
    unique_shape_ids = set()
    for f in frames:
        for sid in shapes_data[str(f)].keys():
            unique_shape_ids.add(str(sid))
            
    # Calculate depth values for layer sorting
    shape_depths = {{}}
    for sid in unique_shape_ids:
        # Find first frame the shape has depth data
        depth_vals = []
        for f in frames:
            if sid in shapes_data[str(f)]:
                val = shapes_data[str(f)][sid]
                if isinstance(val, dict) and "average_depth" in val:
                    depth_vals.append(val["average_depth"])
        shape_depths[sid] = sum(depth_vals) / len(depth_vals) if depth_vals else 0.5
        
    # Sort shapes: closest shapes (lower depth value) last, so they render on top
    sorted_shapes = sorted(list(unique_shape_ids), key=lambda x: shape_depths[x], reverse=True)
            
    # Initialize shapes
    for sid in sorted_shapes:
        shape = rp.Shape(curves)
        
        first_appearance = None
        first_frame = frames[0]
        last_frame = frames[-1]
        
        # Calculate true lifetime
        frames_present = [f for f in frames if sid in shapes_data[str(f)]]
        if frames_present:
            first_frame = frames_present[0]
            last_frame = frames_present[-1]
            raw_val = shapes_data[str(first_frame)][sid]
            first_appearance = raw_val["points"] if isinstance(raw_val, dict) else raw_val
            
        # Naming based on position
        if first_appearance:
            pos_suffix = get_centroid_name(first_appearance, format_w, format_h)
            prefix = "Hole" if "Hole_" in sid else "Shape"
            shape.name = f"{{prefix}}_{{pos_suffix}}_{{sid.split('_')[-1]}}"
        else:
            shape.name = sid
            
        # Set Color
        r, g, b = generate_color(sid)
        shape.getAttributes().set('ro', r)
        shape.getAttributes().set('go', g)
        shape.getAttributes().set('bo', b)
        
        # Set Lifetime attributes
        shape.getAttributes().set('lft', 4.0) # 4 = Frame Range
        shape.getAttributes().set('lfs', float(first_frame))
        shape.getAttributes().set('lfe', float(last_frame))
        
        if first_appearance:
            for pt in first_appearance:
                cv = rp.ShapeControlPoint(pt[0], pt[1])
                shape.append(cv)
                
            if "Hole_" in sid:
                shape.getAttributes().set('bm', 22) # Nuke Minus blend mode
                holes_layer.append(shape)
            else:
                shapes_layer.append(shape)
                
            nuke_shapes[sid] = shape
            
    # Animate points and opacity on every frame
    for f in frames:
        f_data = shapes_data[str(f)]
        for sid, val in f_data.items():
            if str(sid) not in nuke_shapes:
                continue
                
            shape = nuke_shapes[str(sid)]
            pts = val["points"] if isinstance(val, dict) else val
            opacity = val.get("opacity", 1.0) if isinstance(val, dict) else 1.0
            
            left_tangents, right_tangents = compute_tangents(pts)
            
            # Animate Opacity
            opc_curve = shape.getAttributes().getAnimCurve('opc')
            opc_curve.addKey(f, float(opacity))
            opc_curve.keys()[-1].interpolationType = {nuke_interp}
            
            for i, pt in enumerate(pts):
                if i >= len(shape):
                    break
                cv = shape[i]
                
                # Center
                cv.center.getPositionAnimCurve(0).addKey(f, pt[0])
                cv.center.getPositionAnimCurve(1).addKey(f, pt[1])
                cv.center.getPositionAnimCurve(0).keys()[-1].interpolationType = {nuke_interp}
                cv.center.getPositionAnimCurve(1).keys()[-1].interpolationType = {nuke_interp}
                
                # Tangents
                ltx, lty = left_tangents[i]
                rtx, rty = right_tangents[i]
                
                cv.leftTangent.getPositionAnimCurve(0).addKey(f, -ltx)
                cv.leftTangent.getPositionAnimCurve(1).addKey(f, -lty)
                cv.leftTangent.getPositionAnimCurve(0).keys()[-1].interpolationType = {nuke_interp}
                cv.leftTangent.getPositionAnimCurve(1).keys()[-1].interpolationType = {nuke_interp}
                
                cv.rightTangent.getPositionAnimCurve(0).addKey(f, rtx)
                cv.rightTangent.getPositionAnimCurve(1).addKey(f, rty)
                cv.rightTangent.getPositionAnimCurve(0).keys()[-1].interpolationType = {nuke_interp}
                cv.rightTangent.getPositionAnimCurve(1).keys()[-1].interpolationType = {nuke_interp}
                
                # Feather
                if len(pt) >= 5:
                    fx, fy = float(pt[3]), float(pt[4])
                    cv.featherCenter.getPositionAnimCurve(0).addKey(f, fx - pt[0])
                    cv.featherCenter.getPositionAnimCurve(1).addKey(f, fy - pt[1])
                    cv.featherCenter.getPositionAnimCurve(0).keys()[-1].interpolationType = {nuke_interp}
                    cv.featherCenter.getPositionAnimCurve(1).keys()[-1].interpolationType = {nuke_interp}
                else:
                    cv.featherCenter.getPositionAnimCurve(0).addKey(f, 0.0)
                    cv.featherCenter.getPositionAnimCurve(1).addKey(f, 0.0)

    # Clear the onCreate callback so it doesn't run again if the node is copied/pasted
    roto_node.knob('onCreate').setValue('')
    print("Roto shapes created successfully!")
"""

    py_script_clean = py_script.replace('\r\n', '\n').replace('\r', '')
    
    nk_content = f"""set cut_paste_input [stack 0]
version 13.0 v1
push $cut_paste_input
Roto {{
 name UTVFX_AI_Roto
 onCreate {{
{py_script_clean}
 }}
}}"""

    
    # Must use newline='\n' to prevent Nuke's TCL interpreter from choking on \r\n
    with open(out_nk_path, "w", encoding="utf-8", newline='\n') as f:
        f.write(nk_content)
