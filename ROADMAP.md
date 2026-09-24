# Roadmap: rebuilding as Contour VFX

The app is being fixed and rebranded in passes. Each pass ends with a review before the next one starts. Issue IDs refer to [ISSUES.md](ISSUES.md).

## Pass 0: Safety net ☑
- [x] Work branch, pytest, test settings (`pytest.ini`, `tests/conftest.py`)
- [x] Private test plates wired in by path, **outside the repo** (`CONTOUR_FOOTAGE`, default `~/Documents/Test`). Tests only read metadata and numbers; no frame is copied, committed or uploaded
- [x] One test per confirmed bug, marked strict `xfail`, so each fix proves itself
- [x] Fake tests and stale logs removed. `settings.json` and `crash.log` untracked. Big weights and test output ignored
- [x] ISSUES.md and ROADMAP.md

## Pass 1: Software-wide
**Shared contracts** (every node depends on these, so they come first):
- [x] Frame contract: timeline *position* inside the app, plate *frame number* only in file names (C7)
- [x] Inputs resolved from the actual wire, with typed ports (H2)
- [x] Image pipeline: float/16-bit working copy (no JPEG), one colour module with a real OCIO config, ACES and log inputs, highlights kept (C1, H12). Tiered plate (EXR master, 16-bit PNG, JPG) with the ACES studio config.

**Stability:**
- [x] Undo by node id (C5). Keyframes survive reload (C6). Dot nodes save (H1)
- [x] Engine: cache marker (H3), Stop/cancel (H4), Freeze/Bypass (H5), In/Out (H7), hash at start (H8), Add Node menus (H6)
- [x] Projects: unsaved-changes prompt, atomic save, cache kept on Save As (M1, M2). Crash logging (M4)
- [x] AI bridge: off-UI-thread shutdown, timeouts, visible errors (M3)

**Security and install:**
- [x] Pin BiRefNet revision and load locally only (H9). `weights_only=True`, ZIP importer limited to `models/` (H10). Download hashes (M6)
- [x] One install path, a lock file, Python 3.10–3.11, a working `.spec` (H11)

**Rebrand and new UI (Contour VFX):**
- [x] Logo, app icon, banner and splash as editable SVG with a render script. Mark: U-shaped viewfinder bracket with a T-shaped tracking crosshair
- [x] Design system in one place: neutral mid-grey Nuke/Flame-style theme, one accent, Segoe UI (on every Windows machine, so nothing to bundle), SVG line icons (no emoji), colour-coded node types, compact spacing, draggable number fields
- [x] Main window, graph, viewer, timeline and panels restyled. Window title, installer and README renamed

## Pass 2: Node by node (in data-flow order) ☑
Each node is done when it works on the test plates at HD, 4K and frame 1001, Cancel works, outputs keep quality and frame numbers, every option in its panel does something, it has a test, and its panel uses the new design.

- [x] MediaPlate (M8)
- [x] SuperMatte (C3, C4, H13). Core/edge split and multi-channel EXR go with Unified Output (Pass 3)
- [x] RotoToShape (H17)
- [x] CorridorKey (H14)
- [x] Depth (H15)
- [x] AI Roto (H16)
- [x] Grade / OCIO (M9)
- [x] 3D Tracker: rebuilt on the Automated Tracker's COLMAP/GLOMAP solver (H18)

## Pass 3: Export ☑
- [x] Camera to Nuke/Blender/Alembic/USD, reusing the Automated Tracker's tested writers (C2)
- [x] Unified Output: proper RGBA/multi-channel EXR, premult, no gamma on data (H19)
- [x] Roto export hardening (M10)

## Later
- [x] Time left on the progress bar and in command-line renders
- [x] Command-line rendering (`render.bat`, `utvfx/cli.py`)
- [ ] README polish

## Before any public or commercial release
- [ ] Licences: remove or get permission for the non-commercial parts, and ship THIRD_PARTY_NOTICES (M11)
- [ ] Trademark search for "Contour VFX" (USPTO / IP India)
