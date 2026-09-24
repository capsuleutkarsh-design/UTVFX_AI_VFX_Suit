"""What goes next to the exported frames: a Nuke script with a Read per layer, and a JSON sidecar."""
import datetime
import json
import os


def _nk_string(text):
    """A Nuke knob string: forward slashes, quoted, with quotes, backslashes, brackets and $ escaped."""
    text = str(text).replace("\\", "/")
    for ch in ('"', "[", "]", "$", "{", "}"):
        text = text.replace(ch, "\\" + ch)
    return f'"{text}"'


def nuke_reads(path, layers, fps=None, width=None, height=None):
    """A .nk with one Read per exported layer. Data layers (mattes, depth) are read raw."""
    lines = ["#! Contour VFX export", "version 13.0", "Root {", " inputs 0"]
    if layers:
        lines += [f" first_frame {min(l.first for l in layers)}", f" last_frame {max(l.last for l in layers)}"]
    if fps:
        lines.append(f" fps {float(fps):g}")
    if width and height:
        lines.append(f' format "{int(width)} {int(height)} 0 0 {int(width)} {int(height)} 1 contour_plate"')
    lines.append("}")
    for i, layer in enumerate(layers):
        lines += ["Read {", " inputs 0", f" file {_nk_string(layer.pattern)}",
                  f" first {layer.first}", f" last {layer.last}", f" origfirst {layer.first}", f" origlast {layer.last}",
                  " origset true", " on_error black"]
        if layer.kind in ("matte", "depth"):
            lines.append(" raw true")  # data: no colour conversion
        lines += [f" name {_nk_name(layer.name)}", f" label {_nk_string(layer.space)}",
                  f" xpos {i * 120}", " ypos 0", "}"]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def _nk_name(name):
    clean = "".join(c if c.isalnum() else "_" for c in name)
    return "Read_" + (clean or "layer")


def sidecar(path, shot, layers, extra):
    from utvfx.version import APP_NAME, VERSION
    data = {
        "app": f"{APP_NAME} {VERSION}",
        "written": datetime.datetime.now().isoformat(timespec="seconds"),
        "shot": shot,
        "layers": [{"name": l.name, "kind": l.kind, "files": l.pattern.replace("\\", "/"),
                    "first": l.first, "last": l.last, "colour_space": l.space} for l in layers],
    }
    data.update(extra)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
