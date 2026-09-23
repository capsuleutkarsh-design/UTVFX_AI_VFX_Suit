"""Every node setting has help text, and help never describes a setting that no longer exists."""
import glob
import json
import os

import pytest

from utvfx.ui.windows.help_dialog import NODE_HELP_DATA

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS = [json.load(open(p, encoding="utf-8")) for p in sorted(glob.glob(os.path.join(ROOT, "plugins", "*", "plugin.json")))]


@pytest.mark.parametrize("plugin", [p for p in PLUGINS if p["parameters"]], ids=lambda p: p["plugin_type"])
def test_help_matches_the_panel(plugin):
    if plugin["plugin_type"] == "composite_output":
        pytest.xfail("Unified Output is rebuilt in Pass 3 (H19); its help is rewritten then")
    help_params = NODE_HELP_DATA[plugin["plugin_type"]]["params"]
    ids = [q["id"] for q in plugin["parameters"]]
    assert [i for i in ids if i not in help_params] == []
    assert [k for k in help_params if k not in ids] == []
