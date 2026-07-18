import os
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
                pass
            media_hash = hasher.hexdigest()
            return os.path.join(cache_dir, "MediaCache", media_hash)
    return os.path.join(cache_dir, node.node_id)

def get_cached_output(node, preferred_dirs=None, allow_fallback=True, cache_dir=None):
    node_cache = get_node_cache(node, cache_dir)
    preferred_dirs = preferred_dirs or ["fgr", "pha", "Comp", "FG", "Matte", "AlphaHint", "sam_masks"]

    for dirname in preferred_dirs:
        candidate = os.path.join(node_cache, dirname)
        if os.path.isdir(candidate) and os.listdir(candidate):
            return candidate

    if allow_fallback and os.path.isdir(node_cache):
        files = [
            os.path.join(node_cache, name)
            for name in os.listdir(node_cache)
            if os.path.isfile(os.path.join(node_cache, name))
        ]
        if files:
            return node_cache
    return None

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
            preferred = ("pha", "Output/Matte", "Matte", "AlphaHint", "roto_shapes")
        elif view_mode == "COMP" or view_mode == "3D":
            preferred = ("fgr", "Output/Comp", "Output/FG", "Comp", "FG", "roto_shapes")
        else:
            preferred = ()
            
        for dirname in preferred:
            candidate = os.path.join(node_cache, dirname)
            if os.path.isdir(candidate) and os.listdir(candidate):
                return candidate
        
        if view_mode != "SRC":
            files = glob.glob(os.path.join(node_cache, "*"))
            files = [f for f in files if os.path.isfile(f)]
            if files:
                return node_cache

    for upstream_node in get_upstream_nodes(node):
        upstream_path = get_node_media_path(upstream_node, visited, view_mode)
        if upstream_path:
            return upstream_path
    return None
