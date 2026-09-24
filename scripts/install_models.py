"""Install the models from an offline model pack (ContourVFX_Models_<version>.zip.001, .002, ...).

    python_base\python.exe scripts\install_models.py PATH\TO\ContourVFX_Models_<version>.zip.001

Every part must be in the same folder. Each file's SHA-256 is checked against the pack's
manifest before it is put in place. The installer runs this when a pack is chosen.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utvfx.core.model_pack import PackError, install_pack  # noqa: E402


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    print("Contour VFX - installing the offline models", flush=True)
    try:
        count = install_pack(argv[0], ROOT, log=lambda m: print(m, flush=True))
    except (PackError, OSError) as e:
        print(f"\n[ERROR] {e}", flush=True)
        return 1
    print(f"\n[OK] {count} files installed and checked.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
