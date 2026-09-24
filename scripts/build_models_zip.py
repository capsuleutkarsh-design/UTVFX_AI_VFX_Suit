"""Pack every installed model and tool into ZIP parts of up to 2 GB, for offline computers.

    python_base\python.exe scripts\build_models_zip.py [--out FOLDER]

Run on a computer where first_setup.py has downloaded the models (and with internet, to
list the pinned Hugging Face files). BUILD.bat models runs this into build\Output\models.
See utvfx/core/model_pack.py.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utvfx.core.model_pack import PackError, build_pack  # noqa: E402
from utvfx.version import VERSION  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the offline model pack")
    parser.add_argument("--out", default=os.path.join(ROOT, "build", "Output", "models"))
    args = parser.parse_args(argv)
    try:
        build_pack(ROOT, args.out, VERSION, log=lambda m: print(m, flush=True))
    except PackError as e:
        print(f"[ERROR] {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
