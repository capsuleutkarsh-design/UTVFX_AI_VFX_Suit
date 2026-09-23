# UTVFX AI & VFX Suit: Project Audit (Technical)

**Date:** 23 September 2026
**Version checked:** v1.2 (commit `b1b8336`)
**Scope:** all of the project's own code (about 13,000 lines), the install and build scripts, security, and the licences of every AI model and library the app uses.

---

## The short version

The idea and the building blocks are strong. The app is a node graph, like Nuke, joined to a good set of modern AI models, with smart caching and a separate process for the heavy AI work. But a lot of it has been built and never fully wired up or tested.

- **Three headline features do not work at all right now.** These are the camera export to Nuke/Blender, SAMURAI video tracking, and SuperMatte with its default settings on a normal 1920×1080 plate.
- **The app can crash in two common situations.** Using Undo after deleting a node crashes it. Reopening a saved project and clicking a SuperMatte node that has points will almost certainly crash it too.
- **Nodes with several inputs get the wrong data.** The app guesses which input is which from the input's name, not from the wire you actually connected.
- **Some models are licensed for non-commercial use only.** That's fine for personal use. It means the app cannot be sold or used on paid client work as it is today.
- **The tests don't cover the parts that are broken.** That is how these problems got through.

None of this is unusual for a project at this stage, and almost all of it can be fixed. The fixes are listed in order at the end.

### How to read the ratings

| Rating | Meaning |
|---|---|
| 🔴 **Critical** | Crashes the app, loses work, or a main feature doesn't work at all |
| 🟠 **High** | Wrong results or a broken feature that people will hit often |
| 🟡 **Medium** | Annoying, slow, or risky in some situations |
| ⚪ **Low** | Tidy-up and small issues |

**How the findings were checked:** four separate reviews read the code. The main bugs were then confirmed by running small test scripts, without changing any project files. Anything that could not be confirmed is marked *(unconfirmed)*.

---

## 1. Features that are broken right now

### 🔴 Camera export to Nuke and Blender produces files that won't open
`plugins/CompositeOutput/colmap_exporter.py`

- **Unreadable files.** The code writes the two characters `\n` where it should start a new line (this happens in 49 places). The whole `.nk` file comes out as one long line that Nuke can't read, and the Blender script fails with a syntax error.
- **It never runs anyway.** The 3D tracker saves its results in one folder (`sparse/`) and the exporter looks in another (`sparse/0/`), so the export always says "Tracking data is incomplete".
- **The camera and the point cloud don't line up.** One is flipped upside-down and the other isn't.
- **Keys go on the wrong frames.** Camera keys are numbered 1, 2, 3… instead of using the plate's real frame numbers (for example 1001). If the tracker skips a frame, everything after it slips out of sync.

**Fix:** use real line breaks, read from the correct folder, flip the camera the same way as the points, and key the camera on the real frame numbers.

### 🔴 "SAM 2 (SAMURAI)" tracking fails every time
`plugins/SuperMatte/backend.py:414`

- **What happens:** the app saves frames with names like `frame_001001.jpg`. The SAMURAI code expects plain numbers like `00000.jpg`, and crashes when it tries to read `frame_001001` as a number.
- **Why it matters:** this is the only matte mode that remembers the object from frame to frame, so the best tracking option is the one that doesn't work.

**Fix:** save the frames with plain numbered names in a temporary folder, and convert back to the real frame numbers afterwards.

### 🔴 SuperMatte crashes on 1920×1080 plates with the default refiner
`plugins/SuperMatte/backend.py:140-160`

- **What happens:** the ViTMatte model pads the image so its sides are a multiple of 32. A 1080-high plate becomes 1088, and the code never trims those extra 8 rows off. The matte is then a different size from the plate, and the app errors out. (Confirmed: 1920×1080 goes in, 1920×1088 comes out.)
- **On 4K plates** it doesn't crash, but the matte slides out of place by up to about 16 pixels towards the bottom of frame.

**Fix:** crop the result back to its original size, which is one line of code. The MEMatte refiner already does this correctly.

### 🔴 Corrections you click on later frames are ignored
`plugins/SuperMatte/backend.py:525`, `utvfx/ui/canvas.py:198`

- **What happens:** the viewer stores your clicks by position on the timeline (0, 1, 2…), but SuperMatte looks them up by the real frame number (1001, 1002…). On a plate that starts at 1001 they never match.
- **On a 1001 plate:** only your first set of clicks is used. Every correction after that is ignored.
- **On video:** every correction lands one frame early.

**Fix:** use the timeline position everywhere inside the app, and use the real frame number only when naming output files.

### 🟠 Other features that don't do what they say

- **Timeline In/Out.** The range doesn't limit the render. No plugin reads it, and setting it throws away the cache so the whole clip renders again.
- **Freeze.** It never works, because the app clears the Freeze flag just before it checks it. Bypass and Freeze are also lost when you reopen a project.
- **Add Node from the right-click menu, Tab search and dropping a wire on empty space** all do nothing. They look for the main window in the wrong place.
- **Stop.** It only stops the node that is currently selected, not the one actually running. After you stop a node it stays stuck on "executing", and the render queue waits forever.
- **Projects with a Dot node can't be saved.** You get "Failed to save project".
- **Temporal Stabilization in SuperMatte makes flicker worse.** It moves the previous frame's matte the wrong way, which leaves a ghost edge behind moving objects. (Confirmed with a test.)
- **CorridorKey** ignores 8 of its 16 settings, including Premultiplied, Feather, Anti-flicker and Custom BG. Choosing "red" screen crashes it.
- **The OCIO node.** Choosing "Rec709" fails on every frame but still reports success.
- **The Grade node** also grades the alpha channel, which changes the matte.
- **The 3D Tracker cannot run on any machine.** The COLMAP and GLOMAP programs it needs aren't in the repo and aren't downloaded by setup.

---

## 2. Crashes and data loss

### 🔴 Undo after deleting a node crashes the app
`utvfx/core/commands.py`

- **What happens:** when you undo a delete, the node comes back as a new copy with a new ID. Older undo steps still point at the old copy, which no longer exists. Pressing Undo a few more times then crashes the whole program. (Confirmed: add two nodes, connect them, delete one, press Ctrl+Z four times, and it crashes.)

**Fix:** each undo step should remember nodes by ID and look them up again when it runs.

### 🔴 Reopening a project with SuperMatte points crashes the timeline
`utvfx/ui/timeline.py:321`, `utvfx/ui/canvas.py`

- **What happens:** when the project is saved, the frame numbers of your clicks are turned into text ("12" instead of 12). When it's loaded back, the timeline compares text with numbers and crashes.
- **Even if it doesn't crash:** your points stop showing in the viewer, and new clicks on the same frame create a duplicate. One of the two sets of clicks is lost when you next save.

**Fix:** turn the keys back into numbers when loading, and add a test that saves and reloads a project.

### 🟡 Other ways work can be lost

- **Closing** the app never asks "Save changes?".
- **Opening a damaged project file** wipes the current graph before it discovers the file is bad.
- **Saving isn't atomic.** A crash during save can corrupt the project file.
- **"Save As" with a new name** loses all previous renders, because the cache folder is tied to the project name.
- **`run.bat` overwrites `crash.log` every time it starts,** so the log from the last crash is gone.
- **Hard crashes leave no trace.** Nothing records crashes inside Qt or the GPU code, so there's nothing to debug from.

---

## 3. How data moves between nodes

### 🟠 Inputs are guessed from their names, not taken from your wires
`utvfx/core/execution_engine.py:573-585`, `utvfx/core/media_resolver.py`

This is the most important design problem in the engine.

- **How it works now:** when a node has several inputs, the engine looks at each input's name. If the name contains "matte" or "alpha", it follows one rule. Otherwise it simply grabs the first result it finds upstream.
- **What goes wrong:**
  - Unified Output's "Keyed RGBA", "Video Plate" and "Depth Map" inputs can all receive **the same frames**, so the export writes the same images into three folders.
  - The AI Roto "Depth Map" input actually receives the plate.
  - CorridorKey's keyed result is never passed on. Downstream nodes get the rough BiRefNet guide matte instead of the key.

**Fix:** each input should read from the node its wire actually connects to.

### 🟠 An empty cache can count as a finished render
`utvfx/core/media_resolver.py:41-48`

- **What happens:** the app saves a small bookkeeping file (`last_state_hash.txt`) in each node's output folder, and then counts *that file* as proof the node has rendered.
- **Why it matters:** a node that failed without writing anything is treated as done. Downstream nodes then receive an empty folder.

### 🟠 Changing a setting during a render can leave stale results
`utvfx/core/execution_engine.py:641-648`

- **What happens:** the "has this changed?" fingerprint is taken when the render *finishes*, not when it starts. If you move a slider while a render is running, the old result gets saved as if it matched the new setting, and the next run wrongly says "[Cached]".

**Fix:** take the fingerprint, and a copy of the settings, at the start.

---

## 4. Speed and memory

- **The AI engine restarts after every node.** The separate AI process is shut down after each step, so the SAM model (about 2.5 GB) reloads each time. The shutdown also freezes the interface for up to 3 seconds.
- **The AI engine can hang forever.** If it stops responding, the app waits with no timeout, and there's no way to cancel.
- **Playback is slow.** Every frame is read from disk again with no memory cache. Video files are seeked on every frame, which is very slow for H.264, and the A/B wipe loads its second frame on the interface's own thread.
- **GPU memory isn't released** after models that run inside the main app (such as Depth), so the SAM process may run short of VRAM *(unconfirmed)*.
- **The GPU/VRAM readout in the footer never appears.** It needs a package (`pynvml`) that isn't installed.
- **Long shots can run out of RAM.** VideoMaMa keeps every full-size frame in memory, roughly 15 GB for 300 frames at 4K *(estimate)*. VideoMaMa also probably needs more than 16 GB of VRAM.

---

## 5. Security

These matter most if you share the app, projects or model ZIPs with other people.

### 🔴 BiRefNet runs code downloaded from the internet every time
`plugins/CorridorKey/backend.py`

- **Background:** BiRefNet comes with its own Python code, not just weights. To make it load during setup, the app was set to allow that code to run (`trust_remote_code=True`).
- **The risk:** the CorridorKey code also re-downloads BiRefNet's *latest* version on every run, with no version pinned. If the author's Hugging Face account were hacked, or they pushed a breaking change, your machine would run the new code without warning. It has already happened once, harmlessly: the files in `models/BiRefNet` were updated by a download.

**Fix:** pin the download to one known version, or keep a reviewed copy of the code in the repo and stop downloading at run time.

### 🟠 Model files can run hidden code
`models/MEMatte/mematte_loader.py:59`, the SAM 1 loader

- **The risk:** `.pth` files are loaded in a way that lets a tampered file run code on your machine. The MEMatte weights come from Google Drive links with no check that they are the genuine files.

**Fix:** load with `weights_only=True` (the Depth node already does this), prefer `.safetensors` files, and check file hashes.

### 🟠 "Install from Offline ZIP" can install code, not just models
`utvfx/ui/windows/model_downloader_ui.py:126-139`

- **The risk:** a ZIP can contain a `plugins/` folder. That gets unpacked into the app, and the app runs it at the next start. A ZIP shared between artists is an easy way to spread malicious code.

**Fix:** only accept files that go into `models/`, reject code files, and limit the size.

### 🟡 Other security points

- **No download is checked.** Python, pip, FFmpeg and the models are all downloaded without checking they are genuine, and none of them is pinned to a version. An interrupted download can leave a half-written file that then counts as "installed".
- **Nuke export and apostrophes.** A project path with an apostrophe (for example "Bob's shot") produces a broken Nuke script. A crafted file name could run code inside Nuke.
- **The built `.exe` will run any Python file it is given.** That becomes risky if the `.exe` is ever code-signed.
- **The local AI engine has no password,** so other programs on the same PC could talk to it. The risk is low.
- **No secrets leaked.** No passwords, tokens or API keys were found anywhere in the git history.

---

## 6. Installing and building

### 🟠 There are three different ways to install, and they conflict

| Method | What it does |
|---|---|
| `install.bat` | Builds a normal virtual environment (venv), using whatever Python is on the PC |
| `first_setup.py` | Downloads its own portable Python |
| README | Describes a third method |

- **They fight each other.** Running `install.bat` and then `first_setup.py` damages the environment.
- **The build uses a different environment.** The installer build script uses yet another environment from the one `run.bat` uses.

**Fix:** keep one method (`first_setup.py`) and make the others point to it.

### 🟠 The `.exe` build fails on a fresh checkout
`UTVFX_AI_VFX_Tool.spec`

- **It points at a folder that doesn't exist** at that location (`CorridorKeyModule`).
- **The installer would be huge.** It bundles the whole portable Python folder (11 GB here).
- **It compresses the GPU libraries with UPX,** which is known to break them and to trigger antivirus warnings.

### 🟡 Library versions aren't pinned

- **Updates can break the app.** `transformers`, `huggingface_hub`, PySide6 and others have no fixed version, so a future update can break things without warning. That already happened once during setup: the newest `transformers` needed a newer PyTorch.
- **Two copies of OpenCV** are installed at once, and they can conflict.
- **Too-new Python versions fail.** `install.bat` accepts "Python 3.10 or newer", but some packages don't support 3.12 or 3.13 yet.

**Fix:** save the exact working versions to a lock file (`pip freeze`), and require Python 3.10 or 3.11.

### ⚪ Repo tidiness

- **Files that shouldn't be in git:** `crash.log`, the test logs, `settings.json` (it has `D:\...` paths and changes on every launch), `tools/get-pip.py`, and debug files from the COLMAP folder.
- **Committed model files are being overwritten.** The config and code files under `models/` are replaced by downloads, which is why about 37 files show as "modified".
- **A 2.5 GB file isn't ignored.** `models/SAM/tf_model.h5` could be added to git by accident.
- **The README is out of date:**
  - the logo file is missing;
  - the clone address is wrong;
  - "MatteAnyone 2" is advertised, but that plugin doesn't exist.

---

## 7. Licences

This matters as soon as the tool is used for paid work or given to anyone else.

### Cannot be used commercially, and some cannot even be passed on

| Component | Licence | What it means |
|---|---|---|
| **CorridorKey** (code and weights) | CC BY-NC-SA + extra terms | No commercial use. Its terms also say you may not repackage it inside another product, even for free. |
| **VideoMaMa** code | CC BY-NC | No commercial use |
| **GVM** (inside CorridorKey) | CC BY-NC-SA | No commercial use |
| **Depth Anything V2 Base and Large** | CC BY-NC | No commercial use. Only the **Small** model is free for commercial use. |
| **MatAnyone** | S-Lab, non-commercial | No commercial use (the plugin is missing anyway) |

### Free to use, but you must include their licence notices

- **SAM 1, SAM 2/2.1, SAMURAI, GroundingDINO, ViTMatte, BiRefNet (MIT), OpenImageIO, MediaPipe, PyTorch and the other Python libraries:** you must include their licence notices.
- **SAM 3:** Meta's own licence. Commercial use is allowed, but you must ship the licence text, and military uses are banned.
- **Stable Video Diffusion:** free only for businesses under $1 million a year in revenue, with registration and a "Powered by Stability AI" credit.
- **FFmpeg:** GPL. You must include the licence and offer its source code.
- **PySide6 / Qt:** LGPL. Allowed if you include the licence. Remove the unused GPL-only Qt modules (Charts, Quick3D and others) from the installer.

### What this means for you

- **Personal learning and non-commercial use:** fine.
- **Paid client work, or selling or distributing the app:** you would need to remove CorridorKey, VideoMaMa, GVM, MatAnyone and the Depth Base/Large models, or get written permission from their authors.
- **Missing notices:** the installer and model ZIP don't currently include the required licence texts. Add a `THIRD_PARTY_NOTICES` file.
- **Conflicting licence wording:** the `LICENSE` file says "internal use only" while the README says "proprietary". Pick one.

---

## 8. Tests

| Test file | Result |
|---|---|
| `test_signals.py` | Passes. It only checks one error message. |
| `test_regression.py` | Passes, but it misses both crash bugs above. |
| `test_ai_bridge_client.py` | "Passes" without actually testing anything |
| `test_loader.py` | Always passes, even when a module fails to load |
| `test_pyside.py` | Hangs (opens a window) |
| `test_screenshot.py` | Opens the GUI, not an automatic test |

**Missing:** there are no tests for caching, input wiring, undo, saving and reloading, cancelling, or the Nuke exports. Those are exactly where the bugs are. `pytest` isn't installed either.

---

## 9. What's done well

1. **Heavy AI work runs in its own process,** so a model crash or VRAM spike doesn't take down the interface.
2. **Smart caching.** Each node remembers a fingerprint of its settings and everything upstream, and re-renders only when something actually changed.
3. **Every plugin shares one worker base,** which catches errors and shows them in the node's console.
4. **The Roto-to-Nuke export is carefully built.** It uses real Bezier shapes, a steady point count and sensible keyframe reduction, and its `.nk` output is valid.
5. **Settings don't break on another PC.** Saved folder paths from another machine are ignored safely.
6. **Models are loaded from the local `models/` folder first,** so most features work offline.

---

## 10. Suggested order of fixes

**Step 1: Stop the crashes and broken features (a few days of work)**
1. Crop the ViTMatte result (one line), so SuperMatte works on HD.
2. Fix the SAMURAI frame names.
3. Fix the camera exporter: line breaks, folder, axis flip and frame numbers.
4. Fix click keyframes: position against frame number, and numbers against text after loading.
5. Fix the Undo crash: look nodes up by ID.
6. Fix saving with Dot nodes, the Freeze flag and Add Node / Tab search.

**Step 2: Make results trustworthy**
7. Wire inputs by the actual connection, not by name.
8. Stop counting the bookkeeping file as output, and take the cache fingerprint at the start of a render.
9. Make Stop cancel the running node properly, so the queue can't get stuck.
10. Make In/Out actually limit the render, or remove it.

**Step 3: Safety and installation**
11. Pin BiRefNet to one version, load model files safely, and restrict the ZIP importer.
12. Keep one install method, a pinned list of library versions and a working `.exe` build.
13. Add a download step for COLMAP/GLOMAP, or hide the 3D Tracker until it has one.

**Step 4: Protect the work**
14. Ask "save changes?" on close, save safely, keep the cache on Save As, and keep crash logs.
15. Write tests for undo, save/reload, wiring and the Nuke exports.

**Step 5: Before any commercial use**
16. Remove or get permission for the non-commercial models, and ship a licence notices file.
