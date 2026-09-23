import os
import logging
import glob
from utvfx.core.settings_manager import SettingsManager

def get_upstream_nodes(node):
    upstream_nodes = []
    for port in getattr(node, "inputs", []):
        for conn in getattr(port, "connections", []):
            upstream_port = conn.port1 if conn.port1 != port else conn.port2
            if upstream_port and upstream_port.node not in upstream_nodes:
                upstream_nodes.append(upstream_port.node)
    return upstream_nodes

def get_node_cache(node, cache_dir=None):
    if cache_dir is None:
        cache_dir = SettingsManager().get_cache_dir("")
        
    if getattr(node, "plugin_type", "") == "media_plate":
        plate_file = getattr(node, "params", {}).get("plate_file")
        if plate_file and os.path.exists(plate_file):
            import hashlib
            hasher = hashlib.md5()
            hasher.update(plate_file.encode('utf-8'))
            try:
                hasher.update(str(os.path.getmtime(plate_file)).encode('utf-8'))
            except Exception:
                logging.getLogger(__name__).debug("Ignored error", exc_info=True)
            media_hash = hasher.hexdigest()
            return os.path.join(cache_dir, "MediaCache", media_hash)
    return os.path.join(cache_dir, node.node_id)

MEDIA_EXTS = (".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff", ".dpx", ".hdr", ".mov", ".mp4", ".json")

# Bookkeeping lives here so it is never mistaken for a node's output.
META_DIR = ".meta"


def state_hash_path(node_cache):
    return os.path.join(node_cache, META_DIR, "state_hash")


def has_media(folder):
    """True if `folder` holds rendered frames or data, not just bookkeeping."""
    if not os.path.isdir(folder):
        return False
    return any(
        name.lower().endswith(MEDIA_EXTS) and os.path.isfile(os.path.join(folder, name))
        for name in os.listdir(folder)
    )


def get_cached_output(node, preferred_dirs=None, allow_fallback=True, cache_dir=None):
    node_cache = get_node_cache(node, cache_dir)
    preferred_dirs = preferred_dirs or ["fgr", "pha", "Comp", "FG", "Matte", "AlphaHint", "sam_masks"]

    for dirname in preferred_dirs:
        candidate = os.path.join(node_cache, dirname)
        if os.path.isdir(candidate) and os.listdir(candidate):
            return candidate

    if allow_fallback and has_media(node_cache):
        return node_cache
    return None


# Where each node writes each output port, most preferred first. "." is the node's cache folder.
OUTPUT_FOLDERS = {
    "media_plate": {"Video Plate": ["Video Plate"]},
    "super_matte": {"Alpha Matte": ["Matte"]},
    "corridor_keyer": {"Keyed RGBA": ["Output/Processed", "Output/FG"]},
    "ai_depth_estimator": {"Dense Depth Map": ["Depth", "."]},
    "grade": {"Image": ["."]},
    "ocio_colorspace": {"Image": ["."]},
    "roto_to_shape": {"Shape Data": ["roto_shapes"]},
    "ai_roto": {"Shape Data": ["roto_shapes"]},
}

# When a matte input is wired to a node whose output is an image, take that node's matte instead.
ALPHA_FOLDERS = {
    "corridor_keyer": ["Output/Matte", "AlphaHint"],
    "super_matte": ["Matte"],
}


def input_kind(input_name):
    name = input_name.lower()
    if "alpha" in name or "matte" in name:
        return "alpha"
    if "3d" in name or "tracking" in name:
        return "tracking"
    if "shape" in name:
        return "shape"
    if "depth" in name:
        return "depth"
    if "keyed" in name:
        return "keyed"
    return "image"


def _wired_source(port):
    """The output port feeding an input port, or None."""
    for conn in getattr(port, "connections", []):
        for candidate in (conn.port1, conn.port2):
            if candidate is not None and candidate is not port and getattr(candidate, "is_output", False):
                return candidate
    return None


def output_path(node, port_name=None, want="image", cache_dir=None, _visited=None):
    """The folder holding `node`'s output `port_name`, or None if it has not rendered.

    Bypassed nodes and Dots pass their first input through, as in Nuke.
    """
    _visited = _visited or set()
    if node in _visited:
        return None
    _visited.add(node)

    ptype = getattr(node, "plugin_type", "")
    if ptype == "dot_node" or getattr(node, "is_disabled", False):
        inputs = getattr(node, "inputs", [])
        src = _wired_source(inputs[0]) if inputs else None
        return output_path(src.node, src.name, want, cache_dir, _visited) if src else None

    if ptype == "media_plate":
        return resolve_media_input(node, cache_dir=cache_dir)

    node_cache = get_node_cache(node, cache_dir)
    if ptype == "sfm_tracker":
        return node_cache if os.path.isdir(os.path.join(node_cache, "sparse")) else None

    outputs = OUTPUT_FOLDERS.get(ptype, {})
    if want == "alpha" and ptype in ALPHA_FOLDERS:
        folders = ALPHA_FOLDERS[ptype]
    else:
        folders = outputs.get(port_name) or next(iter(outputs.values()), ["."])
        if ptype == "corridor_keyer" and getattr(node, "params", {}).get("foreground_output") == "Straight RGB":
            folders = ["Output/FG", "Output/Processed"]
    for folder in folders:
        candidate = node_cache if folder == "." else os.path.normpath(os.path.join(node_cache, folder))
        if has_media(candidate):
            return candidate
    return None


def has_rendered_output(node, cache_dir=None):
    ptype = getattr(node, "plugin_type", "")
    node_cache = get_node_cache(node, cache_dir)
    if ptype == "sfm_tracker":
        return os.path.isdir(os.path.join(node_cache, "sparse"))
    if ptype in OUTPUT_FOLDERS:
        return any(
            has_media(node_cache if f == "." else os.path.join(node_cache, f))
            for folders in OUTPUT_FOLDERS[ptype].values() for f in folders
        )
    return get_cached_output(node, cache_dir=cache_dir) is not None


def resolve_input(node, input_name, cache_dir=None):
    """What arrives at `node`'s input `input_name`: the output of whatever is wired to it.

    Unwired plate, matte, shape and tracking inputs fall back to searching upstream,
    so graphs that only wire one input keep working. Unwired depth and keyed inputs
    stay empty rather than silently receiving the plate.
    """
    kind = input_kind(input_name)
    port = next((p for p in getattr(node, "inputs", []) if p.name == input_name), None)
    src = _wired_source(port) if port is not None else None
    if src is not None:
        return output_path(src.node, src.name, kind, cache_dir)

    fallback = {
        "alpha": resolve_alpha_input,
        "tracking": resolve_tracking_input,
        "shape": resolve_shape_input,
        "image": resolve_media_input,
    }.get(kind)
    return fallback(node, cache_dir=cache_dir) if fallback else None

def resolve_media_input(node, visited=None, is_start_node=True, cache_dir=None):
    if visited is None:
        visited = set()
    if node in visited:
        return None
    visited.add(node)

    params = getattr(node, "params", {})
    plate_file = params.get("plate_file")
    if getattr(node, "plugin_type", "") == "media_plate" and plate_file and os.path.exists(plate_file):
        cached_output = get_cached_output(node, ["Video Plate"], cache_dir=cache_dir)
        if cached_output:
            return cached_output
            
        if params.get("is_sequence", False) and os.path.isfile(plate_file):
            return os.path.dirname(plate_file)
        return plate_file

    if not is_start_node and not getattr(node, "is_disabled", False):
        cached_output = get_cached_output(node, ["fgr", "Comp", "FG"], cache_dir=cache_dir)
        if cached_output:
            return cached_output

    for upstream_node in get_upstream_nodes(node):
        media_path = resolve_media_input(upstream_node, visited, is_start_node=False, cache_dir=cache_dir)
        if media_path:
            return media_path
    return None

def resolve_alpha_input(node, visited=None, is_start_node=True, cache_dir=None):
    if visited is None:
        visited = set()
    if node in visited:
        return None
    visited.add(node)

    if not is_start_node and not getattr(node, "is_disabled", False):
        cached_alpha = get_cached_output(node, ["pha", "Matte", "AlphaHint", "sam_masks"], allow_fallback=False, cache_dir=cache_dir)
        if cached_alpha:
            return cached_alpha

    for upstream_node in get_upstream_nodes(node):
        alpha_path = resolve_alpha_input(upstream_node, visited, is_start_node=False, cache_dir=cache_dir)
        if alpha_path:
            return alpha_path
    return None

def resolve_tracking_input(node, visited=None, is_start_node=True, cache_dir=None):
    if visited is None:
        visited = set()
    if node in visited:
        return None
    visited.add(node)

    if not is_start_node and not getattr(node, "is_disabled", False):
        if getattr(node, "plugin_type", "") == "sfm_tracker":
            cache_path = get_node_cache(node, cache_dir)
            if os.path.exists(os.path.join(cache_path, "sparse")):
                return cache_path

    for upstream_node in get_upstream_nodes(node):
        track_path = resolve_tracking_input(upstream_node, visited, is_start_node=False, cache_dir=cache_dir)
        if track_path:
            return track_path
    return None

def resolve_shape_input(node, visited=None, is_start_node=True, cache_dir=None):
    if visited is None:
        visited = set()
    if node in visited:
        return None
    visited.add(node)

    if not is_start_node and not getattr(node, "is_disabled", False):
        if getattr(node, "plugin_type", "") in ["roto_to_shape", "ai_roto"]:
            cache_path = get_node_cache(node, cache_dir)
            shape_dir = os.path.join(cache_path, "roto_shapes")
            if os.path.exists(shape_dir):
                return shape_dir

    for upstream_node in get_upstream_nodes(node):
        shape_path = resolve_shape_input(upstream_node, visited, is_start_node=False, cache_dir=cache_dir)
        if shape_path:
            return shape_path
    return None

def get_node_media_path(node, visited=None, view_mode="COMP"):
    """Finds media associated with a node for the viewport viewer."""
    if visited is None:
        visited = set()

    if node in visited:
        return None
    visited.add(node)

    params = getattr(node, "params", {})
    plate_file = params.get("plate_file")
    if getattr(node, "plugin_type", "") == "media_plate" and plate_file and os.path.exists(plate_file):
        node_cache = get_node_cache(node)
        candidate = os.path.join(node_cache, "Video Plate")
        if os.path.isdir(candidate) and os.listdir(candidate):
            return candidate
        if params.get("is_sequence", False) and os.path.isfile(plate_file):
            return os.path.dirname(plate_file)
        return plate_file

    node_cache = get_node_cache(node)

    if os.path.exists(node_cache):
        if view_mode == "MATTE":
            preferred = ("pha", "Output/Matte", "Matte", "AlphaHint", "roto_shapes/previews", "roto_shapes")
        elif view_mode == "COMP" or view_mode == "3D":
            preferred = ("fgr", "Output/Comp", "Output/FG", "Comp", "FG", "Preview", "roto_shapes/previews", "roto_shapes")
        else:
            preferred = ()
            
        for dirname in preferred:
            candidate = os.path.join(node_cache, dirname)
            if os.path.isdir(candidate) and os.listdir(candidate):
                return candidate
        
        if view_mode != "SRC" and has_media(node_cache):
            return node_cache

    for upstream_node in get_upstream_nodes(node):
        upstream_path = get_node_media_path(upstream_node, visited, view_mode)
        if upstream_path:
            return upstream_path
    return None
