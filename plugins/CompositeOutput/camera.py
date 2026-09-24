"""Camera export: the 3D Tracker's solve through the Automated Tracker's tested writers.

The tracker leaves sparse/0 (COLMAP model, binary + TXT) and sparse/solve.json. This builds
the "scene" folder export_tools expects (sparse/*.txt, images/) inside the output's tracking/
folder and writes, next to it: a 1-click Nuke script (.nk), a Nuke .chan, a Blender import
script (and Alembic/.blend when Blender is given), USD when pxr is installed, a PLY point
cloud, camera_track.json, and optionally STMaps with an undistorted plate.

Camera keys land on the plate's own frame numbers. export_tools expects the Automated Tracker's
layout - extracted frames numbered from 1 plus a timeline start - so the tracker's plate-numbered
frames are renamed that way inside the export folder (frame 1001 of a shot starting at 1001
becomes frame_000001) and the first plate number is passed as the timeline start.
"""
import re
import json
import os
import shutil

from .camera_export import export_tools as et
from .camera_export.core import scene_transform as transforms

TXT = ("cameras.txt", "images.txt", "points3D.txt")
# Where the focal length and principal point sit in each COLMAP model's parameter list.
PIXEL_PARAMS = {"SIMPLE_PINHOLE": 3, "SIMPLE_RADIAL": 3, "RADIAL": 3, "SIMPLE_RADIAL_FISHEYE": 3,
                "RADIAL_FISHEYE": 3, "FOV": 4, "PINHOLE": 4, "OPENCV": 4, "OPENCV_FISHEYE": 4,
                "FULL_OPENCV": 4, "THIN_PRISM_FISHEYE": 4}


def scale_cameras(src, dst, factor):
    """Rewrite cameras.txt for frames `factor` times larger (the tracker may solve a half-size plate).

    Focal length and principal point are in pixels and scale; distortion is relative and does not.
    """
    lines = []
    with open(src, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if not parts or line.startswith("#"):
                lines.append(line.rstrip("\n"))
                continue
            model, w, h, params = parts[1], int(parts[2]), int(parts[3]), [float(p) for p in parts[4:]]
            n = PIXEL_PARAMS.get(model, 3)
            params = [p * factor if i < n else p for i, p in enumerate(params)]
            lines.append(" ".join([parts[0], model, str(round(w * factor)), str(round(h * factor))]
                                  + [repr(p) for p in params]))
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def extracted_name(number, first):
    return f"frame_{number - first + 1:06d}.jpg"


def renumber_images_txt(src, dst, frames, first):
    """images.txt with every image named as the Automated Tracker's extractor would have."""
    out = []
    with open(src, encoding="utf-8") as f:
        lines = f.read().splitlines()
    body = [l for l in lines if not l.startswith("#")]
    for header, points in zip(body[0::2], body[1::2]):
        parts = header.split()
        if len(parts) >= 10 and parts[9] in frames:
            parts[9] = extracted_name(frames[parts[9]], first)
        out += [" ".join(parts), points]
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join([l for l in lines if l.startswith("#")] + out) + "\n")


def link_frames(src, dst, frames, first):
    os.makedirs(dst, exist_ok=True)
    for name, number in frames.items():
        if not os.path.isfile(os.path.join(src, name)):
            continue
        target = os.path.join(dst, extracted_name(number, first))
        try:
            os.link(os.path.join(src, name), target)
        except OSError:
            shutil.copy2(os.path.join(src, name), target)


def plate_sequence(solve, log):
    """The plate a Read / background should show, as export_tools.source_sequence_plate() describes it."""
    from utvfx.core.plate import Plate
    cache = solve.get("plate_cache")
    plate = Plate.open(cache) if cache and os.path.isdir(cache) else None
    if plate is None:
        return None
    if plate.m["kind"] == "sequence":
        return et.source_sequence_plate(os.path.dirname(plate.m["source_paths"][0]))
    # A video: point at the full-size EXR master (scene-linear ACEScg), built if needed.
    plate.ensure("master")
    log("Plate for the scripts: the video's EXR master (ACEScg).")
    return et.source_sequence_plate(plate.folder("master"))


def _plain(text):
    """Log text without the emoji the Automated Tracker's console used."""
    return re.sub("[\U00010000-\U0010ffff☀-➿️]", "", text).strip()


def export_camera(tracking_cache, output_dir, params, log, colmap_exe=None):
    """Write every camera format into <output_dir>/tracking. Returns export_all_formats()'s result."""
    sparse = os.path.join(tracking_cache, "sparse")
    model = os.path.join(sparse, "0")
    solve_path = os.path.join(sparse, "solve.json")
    if not (os.path.isfile(solve_path) and all(os.path.isfile(os.path.join(model, n)) for n in TXT)):
        raise RuntimeError("The 3D Tracker has no finished solve to export. Render the tracker first.")
    with open(solve_path, encoding="utf-8") as f:
        solve = json.load(f)

    scene = os.path.join(output_dir, "tracking")
    shutil.rmtree(scene, ignore_errors=True)  # never leave an older shot's files beside the new ones
    os.makedirs(os.path.join(scene, "sparse"))
    working_scale = float(solve.get("working_scale") or 1.0)
    frames = {name: int(n) for name, n in solve["frames"].items()}
    first = min(frames.values())
    if working_scale < 1.0:
        # Solved on the half-size working copy: describe the full-size plate.
        scale_cameras(os.path.join(model, "cameras.txt"), os.path.join(scene, "sparse", "cameras.txt"),
                      1.0 / working_scale)
    else:
        shutil.copy2(os.path.join(model, "cameras.txt"), os.path.join(scene, "sparse", "cameras.txt"))
    shutil.copy2(os.path.join(model, "points3D.txt"), os.path.join(scene, "sparse", "points3D.txt"))
    renumber_images_txt(os.path.join(model, "images.txt"), os.path.join(scene, "sparse", "images.txt"), frames, first)
    mesh = os.path.join(sparse, "environment_mesh.ply")
    if os.path.isfile(mesh):
        shutil.copy2(mesh, os.path.join(scene, "environment_mesh.ply"))  # the writers load it from here
    work_images = os.path.join(tracking_cache, "work", "images")
    if os.path.isdir(work_images):
        link_frames(work_images, os.path.join(scene, "images"), frames, first)

    pixel_aspect = float(solve.get("pixel_aspect") or 1.0)
    source = plate_sequence(solve, log) if abs(pixel_aspect - 1.0) < 1e-6 else None

    transform = None
    scale = float(params.get("scene_scale", 1.0) or 1.0)
    if params.get("level_ground", False):
        points = et.parse_colmap_points3D(os.path.join(scene, "sparse", "points3D.txt"))
        notes = []
        transform = transforms.build(points_for_ground=points.xyz, up=transforms.COLMAP_UP, notes=notes)
        for note in notes:
            log(note)
    if abs(scale - 1.0) > 1e-9:
        transform = transforms.compose(transform or transforms.identity(), transforms.make(scale))

    undistort = bool(params.get("write_undistort", False))
    if undistort and working_scale < 1.0:
        log("Undistorted plate and STMaps need a full-resolution solve (the tracker used the half-size "
            "working copy); skipped.")
        undistort = False

    blender = params.get("blender_exe") or None
    result = et.export_all_formats(
        scene, blender_path=blender if blender and os.path.isfile(blender) else None,
        log_callback=lambda text, colour=None: log(_plain(text)), fps=solve.get("fps"),
        start_frame=first,  # extracted frame k is plate frame first + k - 1
        colmap_exe=colmap_exe, source_sequence=source, scene_transform=transform,
        overscan=float(params.get("overscan", 0.0) or 0.0), write_undistort=undistort, pixel_aspect=pixel_aspect)
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "Camera export failed.")
    return result
