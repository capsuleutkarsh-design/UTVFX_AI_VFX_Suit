# Known issues

This list comes from the September 2026 audit (`audit_reports/`). Each issue has an ID. When a test covers an issue, the test's `xfail` reason quotes that ID, so fixing the bug flips the test and the run tells you to remove the marker.

**Status:** ☐ open · ◐ in progress · ☑ fixed

## Critical: crashes, lost work, main features dead

| ID | Area | Problem | Pass | Test | Status |
|---|---|---|---|---|---|
| C1 | Image I/O | EXR/DPX clipped to 1.0 and squeezed to 8-bit sRGB on load. ACES plates treated as sRGB. Every tool then works from 8-bit PNG/JPEG proxies | 1 | `test_exr_highlights_survive_loading` | ☑ |
| C2 | Camera export | `.nk` / Blender `.py` written with literal `\n`. Exporter reads `sparse/0`, tracker writes `sparse/`. Camera axis flip doesn't match the points. Keys on 1..N, not plate frames | 3 | `test_nuke_camera_export_has_line_breaks` | ☐ |
| C3 | SuperMatte | ViTMatte padding never cropped: 1080-row plates crash, 4K mattes shift ~16 px | 2 | `test_vitmatte_alpha_matches_plate_size` | ☑ |
| C4 | SuperMatte | SAMURAI crashes on every run: frames named `frame_001001.jpg`, SAM2 expects `00000.jpg` | 2 | | ☑ |
| C5 | Undo | Redo creates a new node id. Older commands hold dead objects. Undo after delete segfaults | 1 | `test_add_node_keeps_id_through_undo_redo`, `test_undo_after_delete_restores_graph_without_crashing` | ☑ |
| C6 | Projects | Click keyframes come back as string keys after reload. Timeline paint crashes, points vanish or duplicate | 1 | `test_keyframes_stay_ints_after_save_and_reload` | ☑ |
| C7 | Frame contract | Clicks stored by timeline position, looked up by file frame number. Corrections ignored on 1001 plates, one frame early on video | 1 | `tests/test_frame_contract.py` | ☑ |

## High: wrong results, broken features

| ID | Area | Problem | Pass | Test | Status |
|---|---|---|---|---|---|
| H1 | Projects | Projects with a Dot node can't be saved. Dot nodes can't be deleted or selected | 1 | `test_project_with_dot_node_can_be_saved` | ☑ |
| H2 | Engine | Multi-input nodes resolve inputs by port *name*, not by wire. Unified Output and AI Roto get the wrong frames | 1 | `tests/test_wiring.py` | ☑ |
| H3 | Engine | `last_state_hash.txt` counts as rendered output | 1 | `test_hash_file_alone_is_not_rendered_output` | ☑ |
| H4 | Engine | Stop cancels only the selected node. Cancelled nodes stay "executing". Render queue hangs | 1 | `tests/test_engine.py` | ☑ |
| H5 | Engine | Freeze never works. Bypass/Freeze lost on reload | 1 | `tests/test_engine.py` | ☑ |
| H6 | UI | Right-click Add Node, Tab search and wire-drop search do nothing | 1 | `tests/test_wiring.py` | ☑ |
| H7 | Engine | Timeline In/Out doesn't limit renders, only busts the cache | 1 | `tests/test_engine.py` | ◐ engine passes the range and caches by it; each node must honour it (Pass 2 checklist) |
| H8 | Engine | Cache hash taken at end of render. Mid-render edits get marked cached | 1 | | ☑ |
| H9 | Security | BiRefNet runs its own code with an unpinned revision, re-downloaded on every run | 1 | | ☑ |
| H10 | Security | `torch.load` without `weights_only` (MEMatte, SAM 1). Offline ZIP importer can install plugin code | 1 | | ☑ |
| H11 | Install | Three conflicting install paths. PyInstaller spec points at a missing folder. Unpinned deps | 1 | | ☑ |
| H12 | Colour | One hard-coded linear→sRGB conversion. OCIO node has no config. Viewer double-applies sRGB to EXR outputs | 1 | | ☑ plate loading, EXR colour tags, float pixel probe; OCIO node itself is M9 (Pass 2) |
| H13 | SuperMatte | Temporal Stabilization warps the previous matte the wrong way (adds ghosting) | 2 | | ☑ |
| H14 | CorridorKey | Keys the JPEG proxy. 8 of 16 settings unused. Red screen crashes. Result never reaches downstream nodes | 2 | | ☐ |
| H15 | Depth | 8-bit, per-frame normalised (pumps), preview colormap baked into output, frames numbered from 0 | 2 | | ☐ |
| H16 | AI Roto | Depth units and direction wrong: hides limbs in front | 2 | | ☐ |
| H17 | RotoToShape | Reused shape IDs change point count and the exporter truncates. Layers merged (wrong folder) | 2 | | ☐ |
| H18 | 3D Tracker | COLMAP/GLOMAP binaries not shipped. "SuperPoint" is really SIFT. Moving objects not masked → rebuild on Automated Tracker | 2 | | ◐ COLMAP 4.2.0 (with the global mapper) installed and solving; rebuild on the Automated Tracker in Pass 2 |
| H19 | Unified Output | Gamma 2.2 applied to alpha and depth. "16-bit float" writes 32-bit. sRGB values in EXR. Mattes land in Y, not A | 3 | | ☐ |

## Medium

| ID | Area | Problem | Pass | Status |
|---|---|---|---|---|
| M1 | Projects | Save As loses previous renders (cache tied to project name) | 1 | ☑ |
| M2 | Projects | No "save changes?" on close. Load wipes the graph before parsing. Save not atomic | 1 | ☑ plus autosave/recovery, relink and Settings folders |
| M3 | AI bridge | Blocking shutdown on UI thread after every node. No socket timeout. Startup race. Errors not shown | 1 | ☑ |
| M4 | Logging | `run.bat` overwrites crash.log. No faulthandler. 15 silent `except: pass` | 1 | ☑ (bridge ones go with M3) |
| M5 | Playback | No frame cache. Video seek on every frame. Wipe decodes on UI thread. VRAM readout never shows | 1 | ☑ |
| M6 | Downloads | Partial files count as installed. No hashes. No timeouts | 1 | ☑ |
| M7 | Undo | Clicks, layers, combos, checkboxes and text fields bypass undo | 1 | ☑ |
| M8 | MediaPlate | Drop gives one-frame plate. Mixes sequences in a folder. No DPX/TIFF. fps fixed at 24 | 2 | ☑ |
| M9 | OCIO / Grade | Rec709 fails silently. Grade changes alpha | 2 | ☐ |
| M10 | Roto export | Lifetime attribute names unverified in Nuke. Wrong JSON can be loaded. Path quoting unsafe | 3 | ☐ |
| M11 | Licensing | CorridorKey, VideoMaMa, GVM, MatAnyone, Depth V2 Base/Large are non-commercial. No THIRD_PARTY_NOTICES | before release | ☐ |

## Low
☑ done in Pass 1: dead engine/viewer code, unused signals, dead UI files, shot naming unified, junk files, uv download. Still open: README polish.

Original list: Dead code (`_build_mask_dict`, dead UI files `CorridorKey/ui.py` and `3DTracker/ui.py`, unused signals), shot auto-naming copied three times, README drift (logo, clone URL, MatAnyone 2), stale uv download, repo junk (`.pdb` files, `get-pip.py`, `sqlite3.dll.bak`).
