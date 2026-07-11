import json
import os

def export_roto_to_nuke(json_path, out_py_path):
    with open(json_path, "r") as f:
        shapes = json.load(f)
        
    # The Nuke script we generate
    script_content = f'''import nuke
import nuke.rotopaint as rp

def create_animated_roto():
    shapes_data = {json.dumps(shapes)}
    
    # Sort frames to ensure correct order, ignoring metadata keys
    frames = sorted([int(k) for k in shapes_data.keys() if str(k).isdigit()])
    if not frames:
        print("No shape data found.")
        return
        
    roto_node = nuke.createNode("Roto")
    curves_knob = roto_node['curves']
    
    # Find all unique shape IDs across all frames
    unique_shape_ids = set()
    for f in frames:
        f_data = shapes_data[str(f)]
        if isinstance(f_data, list):
            unique_shape_ids.add("0") # Backwards compatibility for single shape format
        elif isinstance(f_data, dict):
            for sid in f_data.keys():
                unique_shape_ids.add(str(sid))
                
    # Create Nuke shapes
    nuke_shapes = {{}}
    for sid in unique_shape_ids:
        shape = rp.Shape(curves_knob)
        shape.name = f"Auto_Shape_{{sid}}"
        
        # Initialize points using the FIRST frame this shape appears in
        first_appearance = None
        for f in frames:
            f_data = shapes_data[str(f)]
            if isinstance(f_data, list) and sid == "0":
                first_appearance = f_data
                break
            elif isinstance(f_data, dict) and sid in f_data:
                first_appearance = f_data[sid]
                break
                
        if first_appearance:
            for pt in first_appearance:
                cv = rp.ShapeControlPoint(pt[0], pt[1])
                shape.append(cv)
            curves_knob.rootLayer.append(shape)
            nuke_shapes[sid] = shape
            
    format_height = shapes_data.get("format_height", 1080)
    
    # Now animate the points
    for f in frames:
        if str(f) not in shapes_data:
            continue
            
        f_data = shapes_data[str(f)]
        nuke_frame = f + 1 
        
        # Normalize into a dict mapping shape_id to points
        pts_dict = {{}}
        if isinstance(f_data, list):
            pts_dict["0"] = f_data
        elif isinstance(f_data, dict):
            pts_dict = f_data
            
        for sid, pts in pts_dict.items():
            sid_str = str(sid)
            if sid_str not in nuke_shapes:
                continue
                
            shape = nuke_shapes[sid_str]
            for i, pt in enumerate(pts):
                if i >= len(shape):
                    break
                cv = shape[i]
                center = cv.center
                
                center.getPositionAnimCurve(0).addKey(nuke_frame, pt[0])
                center.getPositionAnimCurve(1).addKey(nuke_frame, format_height - pt[1])
                
                center.getPositionAnimCurve(0).keys()[-1].interpolationType = rp.AnimCurve.InterpolationType.LINEAR
                center.getPositionAnimCurve(1).keys()[-1].interpolationType = rp.AnimCurve.InterpolationType.LINEAR

    print("Roto shapes created successfully!")

create_animated_roto()
'''

    with open(out_py_path, "w") as f:
        f.write(script_content)
