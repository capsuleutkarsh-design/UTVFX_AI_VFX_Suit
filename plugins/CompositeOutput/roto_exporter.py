import json
import os

def export_roto_to_nuke(json_path, out_nk_path, interp_mode="Linear"):
    with open(json_path, "r") as f:
        shapes = json.load(f)
        
    # Determine Nuke interpolation type string
    nuke_interp = "rp.AnimCurve.InterpolationType.LINEAR" if interp_mode == "Linear" else "rp.AnimCurve.InterpolationType.SMOOTH"
    json_path_escaped = json_path.replace('\\', '/')
    embedded_json = json.dumps(shapes)
    
    # Create the Python script that Nuke will execute to build the roto node.
    py_script = f"""import json
import os
import nuke
import nuke.rotopaint as rp
import random

json_file = r'{json_path_escaped}'
shapes_data = None
if os.path.exists(json_file):
    try:
        with open(json_file, 'r') as f:
            shapes_data = json.load(f)
    except Exception:
        pass

if not shapes_data:
    try:
        if '/cache/' in json_file.replace('\\\\', '/'):
            cache_root = json_file.replace('\\\\', '/').split('/cache/')[0] + '/cache/'
            if os.path.exists(cache_root):
                for sub in os.listdir(cache_root):
                    candidate = os.path.join(cache_root, sub, 'roto_shapes', 'shapes.json')
                    if os.path.exists(candidate):
                        with open(candidate, 'r') as f:
                            shapes_data = json.load(f)
                        break
    except Exception:
        pass

if not shapes_data:
    try:
        raw_json = '''{embedded_json}'''
        shapes_data = json.loads(raw_json)
    except Exception:
        pass

if not shapes_data:
    nuke.message('shapes.json not found and embedded data failed to load.')
    shapes_data = {{}}

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
    print('No shape data found in shapes.json.')
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
        
        # Set Lifetime attributes (0 = All frames, 2 = Frame range)
        if first_frame == frames[0] and last_frame == frames[-1]:
            shape.getAttributes().set('lft', 0.0)
        else:
            shape.getAttributes().set('lft', 2.0)
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

    def rdp_shape(shape_frames, sid, dev_thresh=2.0):
        if len(shape_frames) <= 2:
            return shape_frames
            
        def get_pts_vec(f):
            val = shapes_data[str(f)][sid]
            pts = val["points"] if isinstance(val, dict) else val
            vec = []
            for p in pts:
                vec.extend([p[0], p[1]])
            return vec
            
        def point_line_dist(v, v1, v2):
            import math
            max_d = 0.0
            l2 = sum((v2[i] - v1[i])**2 for i in range(len(v1)))
            if l2 == 0:
                for i in range(0, len(v), 2):
                    d = math.sqrt((v[i] - v1[i])**2 + (v[i+1] - v1[i+1])**2)
                    if d > max_d: max_d = d
                return max_d
                
            t = sum((v[i] - v1[i]) * (v2[i] - v1[i]) for i in range(len(v))) / l2
            t = max(0.0, min(1.0, t))
            
            for i in range(0, len(v), 2):
                proj_x = v1[i] + t * (v2[i] - v1[i])
                proj_y = v1[i+1] + t * (v2[i+1] - v1[i+1])
                d = math.sqrt((v[i] - proj_x)**2 + (v[i+1] - proj_y)**2)
                if d > max_d: max_d = d
            return max_d

        def rdp_recursive(start_idx, end_idx):
            if end_idx <= start_idx + 1:
                return []
                
            max_dist = 0.0
            max_idx = -1
            
            v1 = get_pts_vec(shape_frames[start_idx])
            v2 = get_pts_vec(shape_frames[end_idx])
            
            for i in range(start_idx + 1, end_idx):
                v = get_pts_vec(shape_frames[i])
                if len(v) != len(v1) or len(v) != len(v2):
                    return list(range(start_idx + 1, end_idx))
                
                d = point_line_dist(v, v1, v2)
                if d > max_dist:
                    max_dist = d
                    max_idx = i
                    
            if max_dist > dev_thresh:
                left = rdp_recursive(start_idx, max_idx)
                right = rdp_recursive(max_idx, end_idx)
                return left + [max_idx] + right
            else:
                return []
                
        res = set([0, len(shape_frames)-1])
        for idx in rdp_recursive(0, len(shape_frames)-1):
            res.add(idx)
            
        return sorted([shape_frames[i] for i in res])

    shape_kfs = {{}}
    for sid_str in nuke_shapes.keys():
        sframes = [f for f in frames if sid_str in shapes_data[str(f)]]
        if sframes:
            shape_kfs[sid_str] = set(rdp_shape(sframes, sid_str, dev_thresh=1.5))
        else:
            shape_kfs[sid_str] = set()

    # Animate points and opacity on active frames
    for f in frames:
        f_data = shapes_data[str(f)]
        for sid_str, shape in nuke_shapes.items():
            if sid_str in f_data:
                if f not in shape_kfs[sid_str]:
                    continue
                val = f_data[sid_str]
                pts = val["points"] if isinstance(val, dict) else val
                opacity = val.get("opacity", 1.0) if isinstance(val, dict) else 1.0
            else:
                continue
                
            # Animate Opacity
            try:
                opc_curve = shape.getAttributes().getAnimCurve('opc')
                opc_curve.addKey(f, float(opacity))
                opc_curve.keys()[-1].interpolationType = {nuke_interp}
            except Exception:
                pass
                
            if pts is None:
                continue
                
            left_tangents, right_tangents = compute_tangents(pts)
            if len(pts[0]) >= 5:
                f_pts = [[pt[3], pt[4], pt[2] if len(pt) > 2 else "smooth"] for pt in pts]
                f_left_tangents, f_right_tangents = compute_tangents(f_pts)
            else:
                f_left_tangents, f_right_tangents = None, None
            
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
                    
                    if f_left_tangents is not None and i < len(f_left_tangents):
                        fltx, flty = f_left_tangents[i]
                        frtx, frty = f_right_tangents[i]
                        try:
                            cv.featherLeftTangent.getPositionAnimCurve(0).addKey(f, -fltx)
                            cv.featherLeftTangent.getPositionAnimCurve(1).addKey(f, -flty)
                            cv.featherLeftTangent.getPositionAnimCurve(0).keys()[-1].interpolationType = {nuke_interp}
                            cv.featherLeftTangent.getPositionAnimCurve(1).keys()[-1].interpolationType = {nuke_interp}
                            
                            cv.featherRightTangent.getPositionAnimCurve(0).addKey(f, frtx)
                            cv.featherRightTangent.getPositionAnimCurve(1).addKey(f, frty)
                            cv.featherRightTangent.getPositionAnimCurve(0).keys()[-1].interpolationType = {nuke_interp}
                            cv.featherRightTangent.getPositionAnimCurve(1).keys()[-1].interpolationType = {nuke_interp}
                        except Exception:
                            pass
                else:
                    cv.featherCenter.getPositionAnimCurve(0).addKey(f, 0.0)
                    cv.featherCenter.getPositionAnimCurve(1).addKey(f, 0.0)

    # Notify Nuke curves engine that hierarchy and animation curves have changed
    curves.changed()

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
 addUserKnob {{20 User l "UTVFX AI Roto"}}
 addUserKnob {{26 info l "" +STARTLINE T "If roto appears as a single frame after paste,\nclick below to rebuild animated curves:"}}
 addUserKnob {{22 rebuild l "Rebuild Animated Roto" +STARTLINE T {{
{py_script_clean}
 }}}}
}}"""

    # Must use newline='\n' to prevent Nuke's TCL interpreter from choking on \r\n
    with open(out_nk_path, "w", encoding="utf-8", newline='\n') as f:
        f.write(nk_content)
