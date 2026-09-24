"""MODEL_DOWNLOADS.md is generated from first_setup.py and must not drift from it."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))


def test_model_list_is_up_to_date():
    import make_model_list
    with open(os.path.join(ROOT, "MODEL_DOWNLOADS.md"), encoding="utf-8") as f:
        assert f.read() == make_model_list.render(), "Run scripts/make_model_list.py"
