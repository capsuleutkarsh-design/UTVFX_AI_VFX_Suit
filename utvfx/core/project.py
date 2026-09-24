"""Project files: safe save, validated load, missing-media relink and autosave.

A project is JSON: {"format": 2, "app_version": ..., "nodes": [...], "connections": [...],
"backdrops": [...]}. Older .utvfx files (no "format") load the same way.
"""
import json
import os
import time

from utvfx.version import VERSION

FORMAT = 2
EXTENSION = ".contour"
FILE_FILTER = "Contour project (*.contour *.utvfx *.json)"


class ProjectError(Exception):
    """The file is not a project this app can open. The message is shown to the user."""


def save(path, scene_data):
    """Write atomically: a crash mid-save leaves the previous file intact."""
    data = dict(scene_data)
    data["format"] = FORMAT
    data["app_version"] = VERSION
    tmp = path + ".saving"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load(path):
    """Read and check a project file without touching the current graph."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, UnicodeDecodeError) as e:
        raise ProjectError(f"Could not read the file: {e}")
    except json.JSONDecodeError as e:
        raise ProjectError(f"The file is damaged (line {e.lineno}): {e.msg}")
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        raise ProjectError("This is not a Contour VFX project.")
    if data.get("format", 1) > FORMAT:
        raise ProjectError("This project was saved by a newer version of Contour VFX.")
    for node in data["nodes"]:
        if not isinstance(node, dict) or "plugin_type" not in node or "node_id" not in node:
            raise ProjectError("The project contains a node this version cannot read.")
    data.setdefault("connections", [])
    data.setdefault("backdrops", [])
    for node in data["nodes"]:
        upgrade_node(node)
    return data


# AI Roto became Matte to Shape's body-parts mode: {old parameter: new parameter}.
_AI_ROTO_PARAMS = {"target_points_limb": "points_limb", "target_points_torso": "points_torso",
                   "target_points_head": "points_head", "hysteresis_high": "hide_behind",
                   "hysteresis_low": "show_again", "corner_threshold": "corner_threshold",
                   "edge_snap_radius": "edge_snap_radius", "temporal_smoothing": "temporal_smoothing",
                   "first_frame": "first_frame", "last_frame": "last_frame"}


def upgrade_node(node):
    """Bring a node saved by an older version up to date (in place)."""
    if node.get("plugin_type") == "ai_roto":
        old = node.get("params") or {}
        node["plugin_type"] = "roto_to_shape"
        node["params"] = {new: old[key] for key, new in _AI_ROTO_PARAMS.items() if key in old}
        node["params"]["mode"] = "Body parts (people)"
        if node.get("name", "").startswith("AI Roto"):
            node["name"] = node["name"].replace("AI Roto", "Matte to Shape", 1)


def missing_media(data):
    """[(node_id, path)] for every Media Plate whose file no longer exists."""
    out = []
    for node in data.get("nodes", []):
        path = (node.get("params") or {}).get("plate_file")
        if node.get("plugin_type") == "media_plate" and path and not os.path.exists(path):
            out.append((node["node_id"], path))
    return out


def relink(data, folder):
    """Point missing plates at files with the same name under `folder`. Returns how many were fixed."""
    wanted = {os.path.basename(p).lower(): node_id for node_id, p in missing_media(data)}
    found = {}
    for root, _, files in os.walk(folder):
        for name in files:
            node_id = wanted.get(name.lower())
            if node_id and node_id not in found:
                found[node_id] = os.path.join(root, name)
    for node in data.get("nodes", []):
        if node.get("node_id") in found:
            node.setdefault("params", {})["plate_file"] = found[node["node_id"]]
    return len(found)


def autosave_path(workspace_dir):
    return os.path.join(workspace_dir, "autosave", "recovery" + EXTENSION)


def write_autosave(workspace_dir, scene_data, project_path=None):
    path = autosave_path(workspace_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = dict(scene_data)
    data["autosave_of"] = project_path
    data["autosave_time"] = time.time()
    save(path, data)
    return path


def read_autosave(workspace_dir):
    """The recovery file left by a session that did not close cleanly, or None."""
    path = autosave_path(workspace_dir)
    if not os.path.exists(path):
        return None
    try:
        return load(path)
    except ProjectError:
        return None


def clear_autosave(workspace_dir):
    try:
        os.remove(autosave_path(workspace_dir))
    except OSError:
        pass


def shot_name_from_path(file_path):
    """A project name guessed from a plate path: "sh010_plate.1001.exr" -> "sh010_plate".

    Frame numbers are stripped; a bare numbered file falls back to its folder name
    unless the folder is a generic one like "renders".
    """
    import re
    name, ext = os.path.splitext(os.path.basename(file_path))
    if ext.lower() not in (".exr", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".dpx"):
        return name
    clean = re.sub(r"[._-]?\d+$", "", name)
    if clean:
        return clean
    folder = os.path.basename(os.path.dirname(file_path))
    if folder and folder.lower() not in ("render", "renders", "output", "outputs", "frames", "images", "img"):
        return folder
    return name
