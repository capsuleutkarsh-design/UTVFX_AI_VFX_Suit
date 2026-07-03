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
    
    # Sort frames to ensure correct order
    frames = sorted([int(k) for k in shapes_data.keys()])
    if not frames:
        print("No shape data found.")
        return
        
    roto_node = nuke.createNode("Roto")
    curves_knob = roto_node['curves']
    
    # Create a new shape
    shape = rp.Shape(curves_knob)
    shape.name = "Auto_Shape"
    
    # Nuke requires the shape to have the points created first
    # We use the first frame's data to initialize the points
    first_frame = str(frames[0])
    first_pts = shapes_data[first_frame]
    
    for pt in first_pts:
        # Nuke points are AnimControl objects
        cv = rp.ShapeControlPoint(pt[0], pt[1])
        shape.append(cv)
        
    curves_knob.rootLayer.append(shape)
    
    format_height = shapes_data.get("format_height", 1080)
    
    # Now animate the points
    for f in frames:
        if str(f) not in shapes_data:
            continue
            
        pts = shapes_data[str(f)]
        if not isinstance(pts, list):
            continue
            
        # Nuke frame offset (usually 1-based, assuming frames here is 0-based index)
        nuke_frame = f + 1 
        
        for i, pt in enumerate(pts):
            if i >= len(shape):
                break
            cv = shape[i]
            # Get center position
            center = cv.center
            
            # Add keys
            center.getPositionAnimCurve(0).addKey(nuke_frame, pt[0])
            
            # Nuke's origin is bottom-left, OpenCV is top-left
            # We invert Y using format_height
            center.getPositionAnimCurve(1).addKey(nuke_frame, format_height - pt[1])
            
            # To avoid weird tangency interpolation jumping, set keys to linear
            center.getPositionAnimCurve(0).keys()[-1].interpolationType = rp.AnimCurve.InterpolationType.LINEAR
            center.getPositionAnimCurve(1).keys()[-1].interpolationType = rp.AnimCurve.InterpolationType.LINEAR

    print("Roto shape created successfully!")

create_animated_roto()
'''

    with open(out_py_path, "w") as f:
        f.write(script_content)
