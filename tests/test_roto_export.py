"""Roto export: the generated Nuke script runs against a strict stand-in for nuke.rotopaint (only
Foundry's documented calls), and the shapes it builds match shapes.json on every frame (points,
feather, visibility) whether or not Nuke honours the interpolation the script asks for."""
import json

import pytest

import nuke_standin as ns
from plugins.CompositeOutput.roto_exporter import build_script, export_roto_to_nuke, validate

FRAMES = range(1001, 1011)


def shapes_data():
    data = {"format_width": 200, "format_height": 100}
    for f in FRAMES:
        k = f - 1001
        data[str(f)] = {"Person/L_Forearm": {"points": [[10 + k * k * 0.5, 10, "smooth", 5 + k * k * 0.5, 5],
                                                        [40, 10 + k, "cusp", 45, 5 + k],
                                                        [40, 40, "smooth", 44, 44]],
                                             "opacity": 1.0 if f < 1006 else 0.0, "average_depth": 0.4}}
        if f >= 1004 and f not in (1007, 1008):   # appears late, and has a gap
            data[str(f)]["Prop/Shape_1"] = {"points": [[100, 50, "smooth"], [120, 50, "smooth"], [110, 70 + k, "smooth"]],
                                            "opacity": 1.0, "average_depth": 0.2}
    return data


def build(monkeypatch, data, linear_sticks=True):
    node, messages = ns.install(monkeypatch, linear_sticks)
    exec(compile(build_script(data), "roto", "exec"), {"__name__": "nuke_roto"})
    return node, messages


@pytest.mark.parametrize("linear_sticks", [True, False])
def test_shapes_match_the_data_on_every_frame(monkeypatch, linear_sticks):
    """With linear_sticks=False Nuke ignores the requested interpolation (the stand-in then
    interpolates smoothly): the script must key whatever frames that gets wrong."""
    data = shapes_data()
    node, messages = build(monkeypatch, data, linear_sticks)
    assert messages == []
    shapes = ns.shapes_of(node)
    assert set(shapes) == {"Person/L_Forearm", "Prop/Shape_1"}
    for sid, shape in shapes.items():
        for f in FRAMES:
            entry = data[str(f)].get(sid)
            visible = shape.getAttributes().getValue(f, "opc")
            assert visible == pytest.approx(entry["opacity"] if entry else 0.0), (sid, f)
            if not entry:
                continue
            for cv, p in zip(ns.outline_at(shape, f), entry["points"]):
                assert cv[0] == pytest.approx(tuple(p[:2]), abs=1.0), (sid, f)
                if len(p) >= 5:
                    assert cv[3] == pytest.approx(tuple(p[3:5]), abs=1.0), (sid, f)


def test_feather_and_tangents_are_offsets_and_cusps_have_none(monkeypatch):
    node, _ = build(monkeypatch, shapes_data())
    forearm = ns.shapes_of(node)["Person/L_Forearm"]
    assert forearm[0].featherCenter.at(1001) == pytest.approx((-5, -5))   # relative to the point
    assert forearm[1].leftTangent.at(1001) == (0, 0) and forearm[1].rightTangent.at(1001) == (0, 0)
    assert forearm[0].rightTangent.at(1001) != (0, 0)


def test_linear_keys_are_thinned(monkeypatch):
    data = shapes_data()
    node, _ = build(monkeypatch, data)
    prop = ns.shapes_of(node)["Prop/Shape_1"]
    # The prop moves linearly: its first and last frames are enough.
    assert prop[2].center.getPositionAnimCurve(1).getNumberOfKeys() == 2


def test_layers_are_named_and_the_node_is_left_clean(monkeypatch):
    node, _ = build(monkeypatch, shapes_data())
    assert [layer.name for layer in node["curves"].rootLayer] == ["Prop", "Person"]  # nearest first
    assert node["onCreate"].value == "" and node["curves"].changes == 1


def test_rebuilding_a_built_node_adds_nothing(monkeypatch):
    node, messages = build(monkeypatch, shapes_data())
    exec(compile(build_script(shapes_data()), "roto", "exec"), {"__name__": "nuke_roto"})
    assert sum(len(layer) for layer in node["curves"].rootLayer) == 2
    assert messages and "already has shapes" in messages[0]


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
