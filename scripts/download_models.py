"""Download missing AI models only (no Python setup).

    python_base\\python.exe scripts\\download_models.py [--yes] [--verify]

Uses the same pinned list, hashes and .part downloads as first_setup.py, so the two
can never disagree about what "installed" means.
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import first_setup  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download missing Contour VFX models")
    parser.add_argument("--yes", "-y", action="store_true", help="do not ask before downloading")
    parser.add_argument("--verify", action="store_true", help="hash files that are already present")
    args = parser.parse_args(argv)

    print("=" * 60)
    print("Contour VFX - model downloader")
    print("=" * 60)
    todo = []
    for task in first_setup.MODELS:
        status = first_setup.item_status(task, verify=args.verify)
        print(f"[{status.upper()}] {task['name']}")
        if status != "ok":
            todo.append(task)
    if not todo:
        print("\nAll models are installed.")
        return 0

    print(f"\n{len(todo)} item(s) are missing or not verified.")
    try:
        answer = "y" if args.yes else input("Download them now? (y/n): ").strip().lower()
    except EOFError:
        answer = "n"
    if answer != "y":
        print("Download cancelled.")
        return 0

    # huggingface_hub is imported in a child process running this same interpreter.
    failed = first_setup.download_models(sys.executable, verify=args.verify)
    print("\n" + "=" * 60)
    if failed:
        print("Not completed: " + ", ".join(failed))
        return 1
    print("Download process finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
