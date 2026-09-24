"""Write MODEL_DOWNLOADS.md from first_setup.py, so the list people read is the list the installer uses.

    python_base\\python.exe scripts\\make_model_list.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import first_setup  # noqa: E402

OUT = os.path.join(ROOT, "MODEL_DOWNLOADS.md")
MEMATTE_LINKS = [
    "https://drive.google.com/file/d/1R5NbgIpOudKjvLz1V9M9SxXr1ovAmu3u/view",
    "https://drive.google.com/file/d/1NOV64zMSFtoKPASqvEvxQKI_PRY9m5IA/view",
    "https://drive.google.com/file/d/122p3sdhJVb7vg4IXELeC9C3HEG9Mlh5z/view",
]


def size_text(n):
    return f"{n / 1e9:.2f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def source(task):
    if task["type"] == "hf_repo":
        return f"[{task['repo_id']}](https://huggingface.co/{task['repo_id']}/tree/{task['revision']}) @ `{task['revision'][:10]}`"
    url = task["url"]
    return f"[{url.rsplit('/', 1)[-1]}]({url})"


def where(task):
    return task.get("path") or task.get("local_dir") or task.get("dest_dir") or task.get("final_name")


def render():
    lines = [
        "# Model and binary downloads",
        "",
        "*Generated from `first_setup.py` by `scripts/make_model_list.py`; do not edit by hand.*",
        "",
        "`first_setup.py` (or `install.bat`) downloads everything below. Each file is pinned to a fixed",
        "Hugging Face commit or release URL and checked against its SHA-256 before it is used, and the app",
        "never downloads models while it runs. To fetch only missing models later:",
        "`python_base\\python.exe scripts\\download_models.py`. Licences: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).",
        "",
        "## Downloaded automatically",
        "",
        "| Item | Goes to | Size | Source (pinned) |",
        "|---|---|---|---|",
    ]
    for task in first_setup.MODELS:
        size = size_text(task["size"]) if task.get("size") else "folder"
        note = " (gated: accept the licence on Hugging Face and log in first)" if task.get("gated") else ""
        lines.append(f"| {task['name']}{note} | `{where(task)}` | {size} | {source(task)} |")
    lines += ["", "## Downloaded by hand", ""]
    for task in first_setup.MANUAL_FILES:
        lines += [f"**{task['name']}** ({size_text(task['size'])}): save as `{task['path']}`.",
                  f"SHA-256 of the tested copy: `{task['sha256']}`.", ""]
    lines += ["The MEMatte authors publish their weights on Google Drive, which cannot be downloaded without a browser:", ""]
    lines += [f"- {link}" for link in MEMATTE_LINKS]
    lines += ["", "Put the ViT-B (DIM) file at the path above; `first_setup.py --verify` checks it against the hash.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(render())
    print(f"Wrote {OUT}")
