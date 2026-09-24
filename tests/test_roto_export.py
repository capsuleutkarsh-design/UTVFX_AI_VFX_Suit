"""Roto export (M10): the generated Nuke script runs (against a stand-in nuke module), uses Nuke's
lifetime attributes, keys plate frames, carries its data inline and refuses files that are not shapes."""
import json
import sys
import types

import pytest

from plugins.CompositeOutput.roto_exporter import build_script, export_roto_to_nuke, validate


def shapes_data():
    data = {"format_width": 200, "format_height": 100}
    for f in range(1001, 1011):
        data[str(f)] = {"Person/L_Forearm": {"points": [[10 + f - 1001, 10, "smooth"], [40, 10, "cusp"], [40, 40, "smooth"]],
                                             "opacity": 1.0 if f < 1006 else 0.0, "average_depth": 0.4}}
        if f >= 1004:
            data[str(f)]["Prop/Shape_1"] = {"points": [[100, 50, "smooth"], [120, 50, "smooth"], [110, 70, "smooth"]],
                                            "opacity": 1.0, "average_depth": 0.2}
    return data


class Curve:
    def __init__(self):
        self.frames = []

    def addKey(self, frame, value):
        self.frames.append((frame, value))

    def keys(self):
        return [types.SimpleNamespace(interpolationType=None) for _ in self.frames] or [types.SimpleNamespace()]


class Element:
    def __init__(self):
        self.curves = [Curve(), Curve()]

    def getPositionAnimCurve(self, i):
        return self.curves[i]


class Point:
    def __init__(self, x, y):
        for name in ("center", "leftTangent", "rightTangent", "featherCenter", "featherLeftTangent", "featherRightTangent"):
            setattr(self, name, Element())


class Attributes(dict):
    def __init__(self):
        super().__init__()
        self.anim = {}

    def set(self, key, value):
        self[key] = value

    def getAnimCurve(self, key):
        return self.anim.setdefault(key, Curve())


class Shape(list):
    def __init__(self, curves):
        super().__init__()
        self.attrs, self.name = Attributes(), ""

    def getAttributes(self):
        return self.attrs


class Layer(list):
    def __init__(self, curves):
        super().__init__()
        self.name = ""


@pytest.fixture
def fake_nuke(monkeypatch):
    root = Layer(None)
    curves = types.SimpleNamespace(rootLayer=root, changed=lambda: None)
    knobs = {"curves": curves, "onCreate": types.SimpleNamespace(setValue=lambda v: None)}
    node = types.SimpleNamespace(__getitem__=None, knob=lambda k: knobs[k])
    node_obj = type("Node", (), {"__getitem__": lambda self, k: knobs[k], "knob": lambda self, k: knobs[k]})()
    nuke = types.ModuleType("nuke")
    nuke.thisNode = lambda: node_obj
    rp = types.ModuleType("nuke.rotopaint")
    rp.Layer, rp.Shape, rp.ShapeControlPoint = Layer, Shape, Point
    rp.AnimCurve = types.SimpleNamespace(InterpolationType=types.SimpleNamespace(LINEAR="linear", SMOOTH="smooth"))
    nuke.rotopaint = rp
    monkeypatch.setitem(sys.modules, "nuke", nuke)
    monkeypatch.setitem(sys.modules, "nuke.rotopaint", rp)
    return root


def run_script(data):
    exec(compile(build_script(data), "roto", "exec"), {"__name__": "nuke_roto"})


def test_script_builds_named_layers_with_lifetimes_and_plate_frames(fake_nuke):
    run_script(shapes_data())
    layers = {l.name: l for l in fake_nuke}
    assert set(layers) == {"Person", "Prop"}
    forearm, prop = layers["Person"][0], layers["Prop"][0]
    assert forearm.name == "L_Forearm" and prop.name == "Shape_1"
    assert forearm.attrs["ltt"] == 0                       # present on every frame
    assert (prop.attrs["ltt"], prop.attrs["ltn"], prop.attrs["ltm"]) == (4, 1004.0, 1010.0)
    keyed = [f for f, _ in forearm[0].center.curves[0].frames]
    assert keyed[0] == 1001 and keyed[-1] == 1010         # keys on plate frames
    opacity = dict(forearm.attrs.anim["opc"].frames)
    assert opacity[1006] == 0.0 and opacity[1005] == 1.0  # the fade is keyed even between shape keys


def test_nk_embeds_its_data_and_has_balanced_braces(tmp_path):
    src = tmp_path / "shapes.json"
    src.write_text(json.dumps(shapes_data()))
    out = tmp_path / "roto.nk"
    export_roto_to_nuke(str(src), str(out))
    nk = out.read_text()
    assert str(tmp_path).replace("\\", "/") not in nk.replace("\\", "/")  # no file path to break or mis-resolve
    assert nk.count("{") == nk.count("}")
    assert "\r" not in nk and "Contour_Roto" in nk


@pytest.mark.parametrize("bad", [{}, {"format_width": 10}, {"format_width": 10, "1001": {"a": {"points": []}}}, []])
def test_wrong_json_is_refused(bad):
    with pytest.raises(ValueError):
        validate(bad)
