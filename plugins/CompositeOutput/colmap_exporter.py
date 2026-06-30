import os
import math

def read_cameras(path):
    cameras = {}
    with open(path, "r") as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.strip().split()
            if not parts:
                continue
            camera_id = int(parts[0])
            model = parts[1]
            width = int(parts[2])
            height = int(parts[3])
            params = [float(p) for p in parts[4:]]
            cameras[camera_id] = {"model": model, "width": width, "height": height, "params": params}
    return cameras

def read_images(path):
    images = {}
    with open(path, "r") as f:
        lines = f.readlines()
        for i in range(0, len(lines), 2):
            if lines[i].startswith("#"):
                continue
            parts = lines[i].strip().split()
            if not parts:
                continue
            image_id = int(parts[0])
            qw, qx, qy, qz = map(float, parts[1:5])
            tx, ty, tz = map(float, parts[5:8])
            camera_id = int(parts[8])
            name = parts[9]
            
            images[image_id] = {
                "q": (qw, qx, qy, qz),
                "t": (tx, ty, tz),
                "camera_id": camera_id,
                "name": name
            }
    return images

def read_points3D(path):
    points = {}
    with open(path, "r") as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.strip().split()
            if not parts:
                continue
            point_id = int(parts[0])
            x, y, z = map(float, parts[1:4])
            r, g, b = map(int, parts[4:7])
            points[point_id] = {"xyz": (x, y, z), "rgb": (r, g, b)}
    return points

def q_to_mat3x3(q):
    qw, qx, qy, qz = q
    mat = [
        [1 - 2*qy**2 - 2*qz**2, 2*qx*qy - 2*qz*qw, 2*qx*qz + 2*qy*qw],
        [2*qx*qy + 2*qz*qw, 1 - 2*qx**2 - 2*qz**2, 2*qy*qz - 2*qx*qw],
        [2*qx*qz - 2*qy*qw, 2*qy*qz + 2*qx*qw, 1 - 2*qx**2 - 2*qy**2]
    ]
    return mat

def colmap_to_nuke_matrix(q, t, scale=1.0):
    R = q_to_mat3x3(q)
    Rt = [
        [R[0][0], R[1][0], R[2][0]],
        [R[0][1], R[1][1], R[2][1]],
        [R[0][2], R[1][2], R[2][2]]
    ]
    tx, ty, tz = t
    t_c2w = [
        -(Rt[0][0]*tx + Rt[0][1]*ty + Rt[0][2]*tz) * scale,
        -(Rt[1][0]*tx + Rt[1][1]*ty + Rt[1][2]*tz) * scale,
        -(Rt[2][0]*tx + Rt[2][1]*ty + Rt[2][2]*tz) * scale
    ]
    mat = [
        [Rt[0][0], -Rt[0][1], -Rt[0][2], t_c2w[0]],
        [Rt[1][0], -Rt[1][1], -Rt[1][2], t_c2w[1]],
        [Rt[2][0], -Rt[2][1], -Rt[2][2], t_c2w[2]],
        [0.0, 0.0, 0.0, 1.0]
    ]
    return mat

def export_to_nuke(cameras, images, points, output_nk_path, scale=1.0):
    with open(output_nk_path, "w") as f:
        f.write("Root {\\n}\\n")
        sorted_images = sorted(images.values(), key=lambda img: img["name"])
        if not sorted_images:
            return
        first_cam = cameras[sorted_images[0]["camera_id"]]
        width = first_cam["width"]
        height = first_cam["height"]
        focal_x = first_cam["params"][0]
        haperture = 24.576
        focal_length = (focal_x / width) * haperture
        vaperture = haperture * (height / width)
        
        f.write("Camera3 {\\n")
        f.write(' name "COLMAP_Camera"\\n')
        f.write(f" haperture {haperture}\\n")
        f.write(f" vaperture {vaperture}\\n")
        f.write(f" focal {focal_length}\\n")
        f.write(" useMatrix true\\n")
        f.write(" matrix {\\n")
        for i in range(16):
            row = i // 4
            col = i % 4
            f.write(f"  {{curve ")
            for frame_idx, img in enumerate(sorted_images, 1):
                mat = colmap_to_nuke_matrix(img["q"], img["t"], scale)
                f.write(f" x{frame_idx} {mat[row][col]}")
            f.write("}\\n")
        f.write(" }\\n")
        f.write("}\\n")
        
    obj_path = output_nk_path.replace(".nk", "_points.obj")
    with open(obj_path, "w") as f:
        for p in points.values():
            x, y, z = p["xyz"]
            r, g, b = p["rgb"]
            x_n = x * scale
            y_n = -y * scale
            z_n = -z * scale
            f.write(f"v {x_n} {y_n} {z_n} {r/255.0} {g/255.0} {b/255.0}\\n")
    
    with open(output_nk_path, "a") as f:
        f.write("ReadGeo2 {\\n")
        f.write(f' file "{obj_path.replace(chr(92), "/")}"\\n')
        f.write(' name "COLMAP_Points"\\n')
        f.write("}\\n")
        f.write("Scene {\\n")
        f.write(' name "COLMAP_Scene"\\n')
        f.write(' inputs 2\\n')
        f.write("}\\n")


def export_to_blender(cameras, images, points, output_py_path, scale=1.0):
    with open(output_py_path, "w") as f:
        f.write("import bpy\\n")
        f.write("import math\\n")
        f.write("import bmesh\\n\\n")
        
        f.write("def setup_scene():\\n")
        sorted_images = sorted(images.values(), key=lambda img: img["name"])
        if not sorted_images:
            return
            
        first_cam = cameras[sorted_images[0]["camera_id"]]
        width = first_cam["width"]
        height = first_cam["height"]
        sensor_width = 36.0
        focal_x = first_cam["params"][0]
        focal_length = (focal_x / width) * sensor_width
        
        f.write("    bpy.context.scene.render.resolution_x = {}\\n".format(width))
        f.write("    bpy.context.scene.render.resolution_y = {}\\n".format(height))
        f.write("\\n")
        f.write("    cam_data = bpy.data.cameras.new('COLMAP_Cam')\\n")
        f.write("    cam_data.sensor_width = {}\\n".format(sensor_width))
        f.write("    cam_data.lens = {}\\n".format(focal_length))
        f.write("    cam_obj = bpy.data.objects.new('COLMAP_Camera', cam_data)\\n")
        f.write("    bpy.context.collection.objects.link(cam_obj)\\n")
        
        for frame_idx, img in enumerate(sorted_images, 1):
            R = q_to_mat3x3(img["q"])
            Rt = [[R[0][0], R[1][0], R[2][0]],
                  [R[0][1], R[1][1], R[2][1]],
                  [R[0][2], R[1][2], R[2][2]]]
            tx, ty, tz = img["t"]
            t_c2w = [-(Rt[0][0]*tx + Rt[0][1]*ty + Rt[0][2]*tz) * scale,
                     -(Rt[1][0]*tx + Rt[1][1]*ty + Rt[1][2]*tz) * scale,
                     -(Rt[2][0]*tx + Rt[2][1]*ty + Rt[2][2]*tz) * scale]
            
            f.write(f"    bpy.context.scene.frame_set({frame_idx})\\n")
            b_mat_str = f"(\\n"
            b_mat_str += f"        ({Rt[0][0]}, {-Rt[0][1]}, {-Rt[0][2]}, {t_c2w[0]}),\\n"
            b_mat_str += f"        ({-Rt[2][0]}, {Rt[2][1]}, {Rt[2][2]}, {-t_c2w[2]}),\\n"
            b_mat_str += f"        ({Rt[1][0]}, {-Rt[1][1]}, {-Rt[1][2]}, {t_c2w[1]}),\\n"
            b_mat_str += f"        (0.0, 0.0, 0.0, 1.0)\\n"
            b_mat_str += f"    )"
            f.write(f"    cam_obj.matrix_world = {b_mat_str}\\n")
            f.write(f"    cam_obj.keyframe_insert(data_path='location', index=-1)\\n")
            f.write(f"    cam_obj.keyframe_insert(data_path='rotation_euler', index=-1)\\n")
        
        f.write("\\n    mesh = bpy.data.meshes.new('COLMAP_Points')\\n")
        f.write("    obj = bpy.data.objects.new('COLMAP_PointCloud', mesh)\\n")
        f.write("    bpy.context.collection.objects.link(obj)\\n")
        f.write("    bm = bmesh.new()\\n")
        
        for p in points.values():
            x, y, z = p["xyz"]
            x_b = x * scale
            y_b = -z * scale
            z_b = y * scale
            f.write(f"    bm.verts.new(({x_b}, {y_b}, {z_b}))\\n")
            
        f.write("    bm.to_mesh(mesh)\\n")
        f.write("    bm.free()\\n")
        f.write("\\nsetup_scene()\\n")
