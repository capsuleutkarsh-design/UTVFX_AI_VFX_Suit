"""Nuke Roto export for Matte to Shape, outline or body parts (shapes.json).

The result is a .nk to paste (Ctrl+V) into Nuke: a Roto node whose onCreate script builds
the animated shapes. The shape data is embedded in the script as base64, so the .nk works
on any machine, never reads a file by path and cannot pick up another shot's shapes.

shapes.json: {"format_width": W, "format_height": H,
              "<frame>": {"<Layer>/<Shape>": {"points": [[x, y, "smooth"|"cusp"(, fx, fy)], ...],
                                              "opacity": 0-1, "average_depth": ...}}}
Points are in Nuke coordinates (origin bottom-left); frames are plate frame numbers.

The script uses only nuke.rotopaint calls documented by Foundry and seen in working scripts:
AnimControlPoint.addPositionKey(t, (x, y)) and getPositionAnimCurve(i), AnimCurve.evaluate /
getNumberOfKeys / getKey, AnimCurveKey.interpolationType, rp.InterpolationType,
AnimAttributes.set(t, "opc", v) / set("ltt", 0) / getCurve("opc"). Tangents and feather are offsets from
the point (feather tangents from the feather point), as Nuke stores them. The old script
called AnimCurve.keys() and rp.AnimCurve.InterpolationType, which Nuke does not have: it
stopped before the first key, leaving a still, unfeathered shape.
"""
import base64
import json

SCRIPT = r'''
import base64, json, math, random
import nuke
import nuke.rotopaint as rp

DATA = json.loads(base64.b64decode("__DATA__").decode("utf-8"))
LINEAR = __LINEAR__
TOLERANCE = 1.0  # px: a frame is keyed when the curves between its neighbouring keys miss it by more

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

def elements(cv):
    return (cv.center, cv.leftTangent, cv.rightTangent, cv.featherCenter, cv.featherLeftTangent, cv.featherRightTangent)

def key_frame(shape, sid, f):
    """Key every point, tangent and feather point of `shape` on frame f."""
    pts = DATA[str(f)][sid]["points"]
    left, right = tangents(pts)
    feather = len(pts[0]) >= 5
    if feather:
        f_left, f_right = tangents([[p[3], p[4], p[2]] for p in pts])
    for i, p in enumerate(pts[:len(shape)]):
        cv = shape[i]
        cv.center.addPositionKey(f, (p[0], p[1]))
        cv.leftTangent.addPositionKey(f, (-left[i][0], -left[i][1]))
        cv.rightTangent.addPositionKey(f, (right[i][0], right[i][1]))
        if feather:
            cv.featherCenter.addPositionKey(f, (p[3] - p[0], p[4] - p[1]))
            cv.featherLeftTangent.addPositionKey(f, (-f_left[i][0], -f_left[i][1]))
            cv.featherRightTangent.addPositionKey(f, (f_right[i][0], f_right[i][1]))

def set_interpolation(shape):
    """Linear (or smooth) between keys, if this Nuke lets a script set it."""
    kind = getattr(getattr(rp, "InterpolationType", None),
                   "eLinearInterpolationType" if LINEAR else "eCubicInterpolationType", None)
    if kind is None:
        return
    for i in range(len(shape)):
        for element in elements(shape[i]):
            for dim in (0, 1):
                curve = element.getPositionAnimCurve(dim)
                for k in range(curve.getNumberOfKeys()):
                    try:
                        curve.getKey(k).interpolationType = kind
                    except Exception:
                        return

def drift(shape, sid, f):
    """How far Nuke's interpolated points (and feather) are from the traced ones on frame f, px."""
    worst = 0.0
    for i, p in enumerate(DATA[str(f)][sid]["points"][:len(shape)]):
        c = shape[i].center
        worst = max(worst, abs(c.getPositionAnimCurve(0).evaluate(f) - p[0]),
                    abs(c.getPositionAnimCurve(1).evaluate(f) - p[1]))
        if len(p) >= 5:
            fc = shape[i].featherCenter
            worst = max(worst, abs(fc.getPositionAnimCurve(0).evaluate(f) - (p[3] - p[0])),
                        abs(fc.getPositionAnimCurve(1).evaluate(f) - (p[4] - p[1])))
    return worst

def keyframes(frames, sid):
    """Frames worth keying: first, last, and wherever linear interpolation would drift (RDP)."""
    def vec(f):
        return [c for p in DATA[str(f)][sid]["points"] for c in (p[:2] + p[3:5])]
    def worst(a, b):
        va, vb = vec(frames[a]), vec(frames[b])
        best, at = 0.0, None
        for i in range(a + 1, b):
            v = vec(frames[i])
            if len(v) != len(va) or len(v) != len(vb):
                return float("inf"), i
            t = (frames[i] - frames[a]) / float(frames[b] - frames[a])  # by frame: there can be gaps
            d = max(abs(v[k] - (va[k] + t * (vb[k] - va[k]))) for k in range(len(v)))
            if d > best:
                best, at = d, i
        return best, at
    keep, stack = {0, len(frames) - 1}, [(0, len(frames) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        d, i = worst(a, b)
        if d > TOLERANCE:
            keep.add(i); stack += [(a, i), (i, b)]
    return {frames[i] for i in keep}

def depth(sid, frames):
    values = [DATA[str(f)][sid].get("average_depth") for f in frames if sid in DATA[str(f)]]
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else 0.0

def build_shape(curves, layer, sid, frames):
    present = [f for f in frames if sid in DATA[str(f)]]
    shape = rp.Shape(curves)
    shape.name = sid.rpartition("/")[2] or sid
    for p in DATA[str(present[0])][sid]["points"]:
        shape.append(rp.ShapeControlPoint(p[0], p[1]))
    attrs = shape.getAttributes()
    random.seed(sid)
    for channel in ("ro", "go", "bo"):  # overlay colour, so shapes are told apart in the viewer
        attrs.set(channel, random.uniform(0.3, 1.0))
    attrs.set("ltt", 0)  # lifetime: all frames; when it shows is keyed on its opacity
    layer.append(shape)

    keys = keyframes(present, sid)
    for f in sorted(keys):
        key_frame(shape, sid, f)
    set_interpolation(shape)
    # Whatever interpolation this Nuke uses between keys, also key any frame it misses.
    for _ in range(4):
        extra = [f for f in present if f not in keys and drift(shape, sid, f) > TOLERANCE]
        if not extra:
            break
        for f in extra:
            key_frame(shape, sid, f)
            keys.add(f)
        set_interpolation(shape)

    # Opacity on every frame of the shot, 0 where the shape is absent (before it appears, after
    # it goes, and in any gap). Keyed on every change, with the frame before it held, so the
    # shape shows or hides on exactly that frame instead of fading between keys.
    opacity = [(f, float(DATA[str(f)][sid].get("opacity", 1.0)) if sid in DATA[str(f)] else 0.0) for f in frames]
    for n, (f, value) in enumerate(opacity):
        if n == 0 or value != opacity[n - 1][1]:
            if n > 0:
                attrs.set(opacity[n - 1][0], "opc", opacity[n - 1][1])
            attrs.set(f, "opc", value)
    curve = attrs.getCurve("opc")
    step = getattr(getattr(rp, "InterpolationType", None), "eStepInterpolationType", None)
    # Smooth interpolation would bulge between two equal keys and flash a hidden shape on:
    # step if this Nuke allows it, and a key on any frame that still comes out wrong.
    for _ in range(2):
        if step is not None:
            try:
                for k in range(curve.getNumberOfKeys()):
                    curve.getKey(k).interpolationType = step
            except Exception:
                pass
        wrong = [(f, value) for f, value in opacity if abs(curve.evaluate(f) - value) > 1e-3]
        if not wrong:
            break
        for f, value in wrong:
            attrs.set(f, "opc", value)

def build():
    frames = sorted(int(k) for k in DATA if str(k).isdigit())
    node = nuke.thisNode()
    curves = node["curves"]
    root = curves.rootLayer
    if any(True for _ in root):
        nuke.message("This Roto node already has shapes. Paste the .nk again for a fresh copy.")
        return
    layers, built, failed = {}, 0, []
    ids = sorted({sid for f in frames for sid in DATA[str(f)]})
    for sid in sorted(ids, key=lambda s: depth(s, frames)):
        layer_name = sid.rpartition("/")[0] or "Shapes"
        try:
            if layer_name not in layers:
                layers[layer_name] = rp.Layer(curves)
                layers[layer_name].name = layer_name
                root.append(layers[layer_name])
            build_shape(curves, layers[layer_name], sid, frames)
            built += 1
        except Exception as error:
            failed.append("%s: %s" % (sid, error))
    curves.changed()
    node.knob("onCreate").setValue("")
    if failed:
        nuke.message("Contour VFX: %d shapes built, %d failed:\n%s" % (built, len(failed), "\n".join(failed[:10])))
    print("Contour VFX: %d roto shapes on frames %d-%d." % (built, frames[0], frames[-1]) if frames else "No shapes.")

build()
'''


def build_script(shapes, interp_mode="Linear"):
    """The Python that builds the shapes inside Nuke."""
    data = base64.b64encode(json.dumps(shapes).encode("utf-8")).decode("ascii")
    return SCRIPT.replace("__DATA__", data).replace("__LINEAR__", str(interp_mode == "Linear")).strip("\n")


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
