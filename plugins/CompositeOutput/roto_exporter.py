"""Nuke Roto export for Roto to Shape and AI Roto (shapes.json).

The result is a .nk to paste (Ctrl+V) into Nuke: a Roto node whose onCreate script builds
the animated shapes. The shape data is embedded in the script as base64, so the .nk works
on any machine, never reads a file by path and cannot pick up another shot's shapes.

shapes.json: {"format_width": W, "format_height": H,
              "<frame>": {"<Layer>/<Shape>": {"points": [[x, y, "smooth"|"cusp"(, fx, fy)], ...],
                                              "opacity": 0-1, "average_depth": ...}}}
Points are in Nuke coordinates (origin bottom-left); frames are plate frame numbers.
"""
import base64
import json

# Nuke RotoPaint shape attributes (AnimAttributes keys).
LIFETIME_TYPE, LIFETIME_START, LIFETIME_END = "ltt", "ltn", "ltm"
LIFETIME_ALL, LIFETIME_RANGE = 0, 4

SCRIPT = r'''
import base64, json, math, random
import nuke
import nuke.rotopaint as rp

DATA = json.loads(base64.b64decode("__DATA__").decode("utf-8"))
INTERP = __INTERP__

def tangents(pts):
    left, right = [], []
    n = len(pts)
    for i in range(n):
        if len(pts[i]) > 2 and pts[i][2] == "cusp":
            left.append((0.0, 0.0)); right.append((0.0, 0.0)); continue
        prev, cur, nxt = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
        d_prev = math.hypot(cur[0] - prev[0], cur[1] - prev[1])
        d_next = math.hypot(nxt[0] - cur[0], nxt[1] - cur[1])
        total = d_prev + d_next
        if total == 0:
            left.append((0.0, 0.0)); right.append((0.0, 0.0)); continue
        dx, dy = (nxt[0] - prev[0]) / 3.0, (nxt[1] - prev[1]) / 3.0
        left.append((dx * d_prev / total, dy * d_prev / total))
        right.append((dx * d_next / total, dy * d_next / total))
    return left, right

def key(curve, frame, value):
    curve.addKey(frame, value)
    curve.keys()[-1].interpolationType = INTERP

def key_xy(element, frame, x, y):
    key(element.getPositionAnimCurve(0), frame, x)
    key(element.getPositionAnimCurve(1), frame, y)

def keyframes(frames, sid, tolerance=1.5):
    """Frames worth keying: first, last, and wherever linear interpolation would drift (RDP)."""
    def vec(f):
        return [c for p in DATA[str(f)][sid]["points"] for c in p[:2]]
    def worst(a, b):
        va, vb = vec(frames[a]), vec(frames[b])
        best, at = 0.0, None
        for i in range(a + 1, b):
            v = vec(frames[i])
            if len(v) != len(va) or len(v) != len(vb):
                return float("inf"), i
            t = (i - a) / float(b - a)
            d = max(math.hypot(v[k] - (va[k] + t * (vb[k] - va[k])), v[k + 1] - (va[k + 1] + t * (vb[k + 1] - va[k + 1])))
                    for k in range(0, len(v), 2))
            if d > best:
                best, at = d, i
        return best, at
    keep, stack = {0, len(frames) - 1}, [(0, len(frames) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        d, i = worst(a, b)
        if d > tolerance:
            keep.add(i); stack += [(a, i), (i, b)]
    return {frames[i] for i in keep}

frames = sorted(int(k) for k in DATA if str(k).isdigit())
node = nuke.thisNode()
curves = node["curves"]
root = curves.rootLayer
layers, shapes = {}, {}
ids = sorted({sid for f in frames for sid in DATA[str(f)]})

def depth(sid):
    values = [DATA[str(f)][sid].get("average_depth") for f in frames if sid in DATA[str(f)]]
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else 0.0

for sid in sorted(ids, key=depth):
    layer_name, _, shape_name = sid.rpartition("/")
    layer_name = layer_name or "Shapes"
    if layer_name not in layers:
        layers[layer_name] = rp.Layer(curves)
        layers[layer_name].name = layer_name
        root.append(layers[layer_name])
    present = [f for f in frames if sid in DATA[str(f)]]
    first_pts = DATA[str(present[0])][sid]["points"]
    shape = rp.Shape(curves)
    shape.name = shape_name or sid
    for p in first_pts:
        shape.append(rp.ShapeControlPoint(p[0], p[1]))
    attrs = shape.getAttributes()
    random.seed(sid)
    for channel in ("ro", "go", "bo"):  # overlay colour, so shapes are told apart in the viewer
        attrs.set(channel, random.uniform(0.3, 1.0))
    # Visible only on the frames it was found on.
    if present[0] == frames[0] and present[-1] == frames[-1]:
        attrs.set("__LT_TYPE__", __LT_ALL__)
    else:
        attrs.set("__LT_TYPE__", __LT_RANGE__)
        attrs.set("__LT_START__", float(present[0]))
        attrs.set("__LT_END__", float(present[-1]))
    layers[layer_name].append(shape)
    shapes[sid] = (shape, present)

for sid, (shape, present) in shapes.items():
    keys = keyframes(present, sid)
    last_opacity, last_frame, keyed_opacity = None, None, set()
    opc = shape.getAttributes().getAnimCurve("opc")
    for f in present:
        value = DATA[str(f)][sid]
        opacity = float(value.get("opacity", 1.0))
        if opacity != last_opacity or f in keys:
            # Every change of visibility is keyed, with the frame before it held, so the
            # change happens on that frame instead of fading in from the last key.
            if last_opacity is not None and opacity != last_opacity and last_frame not in keyed_opacity:
                key(opc, last_frame, last_opacity)
                keyed_opacity.add(last_frame)
            key(opc, f, opacity)
            keyed_opacity.add(f)
        last_opacity, last_frame = opacity, f
        if f not in keys:
            continue
        pts = value["points"]
        left, right = tangents(pts)
        feather = len(pts[0]) >= 5
        if feather:
            f_left, f_right = tangents([[p[3], p[4], p[2]] for p in pts])
        for i, p in enumerate(pts[:len(shape)]):
            cv = shape[i]
            key_xy(cv.center, f, p[0], p[1])
            key_xy(cv.leftTangent, f, -left[i][0], -left[i][1])
            key_xy(cv.rightTangent, f, right[i][0], right[i][1])
            if feather:
                key_xy(cv.featherCenter, f, p[3] - p[0], p[4] - p[1])
                key_xy(cv.featherLeftTangent, f, -f_left[i][0], -f_left[i][1])
                key_xy(cv.featherRightTangent, f, f_right[i][0], f_right[i][1])

curves.changed()
node.knob("onCreate").setValue("")
print("Contour VFX: %d roto shapes on frames %d-%d." % (len(shapes), frames[0], frames[-1]) if frames else "No shapes.")
'''


def build_script(shapes, interp_mode="Linear"):
    """The Python that builds the shapes inside Nuke."""
    data = base64.b64encode(json.dumps(shapes).encode("utf-8")).decode("ascii")
    interp = ("rp.AnimCurve.InterpolationType.LINEAR" if interp_mode == "Linear"
              else "rp.AnimCurve.InterpolationType.SMOOTH")
    replacements = {"__DATA__": data, "__INTERP__": interp, "__LT_TYPE__": LIFETIME_TYPE,
                    "__LT_START__": LIFETIME_START, "__LT_END__": LIFETIME_END,
                    "__LT_ALL__": str(LIFETIME_ALL), "__LT_RANGE__": str(LIFETIME_RANGE)}
    script = SCRIPT
    for token, value in replacements.items():
        script = script.replace(token, value)
    return script.strip("\n")


def validate(shapes):
    """Reject files that are not shape data (the old exporter would load any shapes.json it found)."""
    if not isinstance(shapes, dict) or "format_width" not in shapes:
        raise ValueError("Not a Contour VFX shapes.json (no format_width).")
    frames = [k for k in shapes if str(k).isdigit()]
    if not frames:
        raise ValueError("shapes.json has no frames.")
    for f in frames:
        for sid, value in shapes[f].items():
            if not isinstance(value, dict) or not value.get("points"):
                raise ValueError(f"Shape {sid} on frame {f} has no points.")


def export_roto_to_nuke(json_path, out_nk_path, interp_mode="Linear"):
    with open(json_path, "r", encoding="utf-8") as f:
        shapes = json.load(f)
    validate(shapes)
    script = build_script(shapes, interp_mode)
    width, height = int(shapes["format_width"]), int(shapes["format_height"])
    # Tcl braces hold the script as-is; it contains only balanced braces (base64 has none).
    nk = "\n".join([
        "set cut_paste_input [stack 0]",
        "version 13.0 v1",
        "push $cut_paste_input",
        "Roto {",
        f' format "{width} {height} 0 0 {width} {height} 1 contour_roto"',
        " onCreate {",
        script,
        " }",
        ' addUserKnob {20 contour l "Contour VFX"}',
        ' addUserKnob {26 info l "" +STARTLINE T "If the shapes did not build on paste, click Rebuild."}',
        " addUserKnob {22 rebuild l \"Rebuild Shapes\" +STARTLINE T {",
        script,
        " }}",
        " name Contour_Roto",
        " selected true",
        "}",
    ])
    with open(out_nk_path, "w", encoding="utf-8", newline="\n") as f:  # Nuke's Tcl dislikes \r\n
        f.write(nk + "\n")
