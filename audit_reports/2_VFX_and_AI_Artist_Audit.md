# UTVFX AI & VFX Suit: Review from a VFX and AI Artist's Point of View

**Date:** 23 September 2026
**Version checked:** v1.2

**Question this review answers:** if a working compositor or roto/prep artist sat down with this tool on a real shot, what would help them, what would get in their way, and could they trust what comes out?

This review is based on reading the app's code, its interface definitions and its help text. The main problems were checked with small tests. It was not tested on real production footage. Speed and memory figures are estimates and are marked as such.

---

## The short version

**The good news:** the tool has the right idea. It's a node graph that feels familiar to Nuke users, and it gathers the best current AI models for roto, matting, keying and depth in one place. The **Roto-to-Nuke export is genuinely useful already**: it produces real, editable Bezier shapes with sensible keyframes.

**The main problem:** the moment you load a plate, the app turns it into an **8-bit sRGB PNG/JPEG copy**, and every tool works from that copy. For a professional shot (EXR, DPX, log, ACES) that throws away the quality you care about, and the colours come out wrong. On top of that, several hand-offs to Nuke are broken:
- the camera export doesn't work;
- the "Unified Output" node can mix up its inputs;
- the keyer's result never reaches the output.

| Area | Verdict today |
|---|---|
| Roto → Nuke Roto shapes (first pass on HD) | ✅ Nearly ready; clean up by hand in Nuke |
| CorridorKey (if you take the EXRs straight from its cache folder) | ✅ Useful first-pass key |
| SuperMatte with SAM 1/SAM 3 | 🟡 OK for temp/previs mattes |
| Depth maps | 🟡 Rough fog/haze helper only |
| Anything needing accurate colour (linear, ACES, log) | ❌ Not usable yet |
| 3D camera export to Nuke | ❌ Broken |
| SAMURAI video tracking | ❌ Crashes every time |
| VideoMaMa on a 16 GB card | ❌ Probably runs out of memory |
| Multi-shot / farm / batch work | ❌ Not supported |

**In one line:** it's a promising AI prep tool that could sit next to Nuke, but it isn't ready for real shots yet. The roto export is the part that could earn its place in a pipeline first.

---

## 1. Getting footage in

### What works
- **Frame numbers are kept for image sequences.** A plate numbered from 1001 keeps its numbers.
- **MOV/ProRes and MP4 load,** through OpenCV with a backup reader.
- **The viewer detects a whole sequence** automatically when you drop in one frame.

### What gets in the way
- **Every plate is turned into 8-bit.** The app saves a PNG and a JPEG copy of every frame and works from those. Most tools prefer the **JPEG**, which by default stores colour at half resolution (4:2:0) *(inferred)*. That hurts exactly where a keyer or matting model needs detail: edges, hair and motion blur.
- **Dropping one frame gives you a one-frame plate.** "Load as image sequence" is off by default, and drag-and-drop doesn't turn it on. The viewer shows the whole sequence while the node only gets one frame, which will confuse junior artists.
- **Different sequences in one folder get mixed together.** The app grabs every image in the folder, so a plate and its denoised version get interleaved.
- **Some formats can't be picked.** The file browser lists only MP4, MOV, PNG, JPG and EXR, so there's no DPX or TIFF, and TIFF sequences are rejected.
- **Frame rate is always 24** for sequences. It isn't stored and isn't exported.
- **Pixel aspect, anamorphic footage and overscan aren't handled.** EXRs with a cropped data window may load at the wrong size *(inferred)*.
- **The timeline In/Out points don't limit the render.** They only make the node re-render the full clip.

---

## 2. Colour

This is the biggest problem for professional use.

- **One fixed conversion is applied to everything.** Every EXR, DPX and HDR plate gets a *linear → sRGB* conversion, highlights above 1.0 are clipped, and the result is squeezed into 8-bit.
  - **DPX** is usually log or Cineon, so it comes out washed out and wrong.
  - **ACEScg EXRs** are treated as ordinary sRGB, so hues shift.
  - **If OpenImageIO is missing,** linear plates are only clipped and come out dark.
- **Giving the AI sRGB-style images is correct in itself,** since SAM, ViTMatte and Depth Anything expect that. The problem is that nothing is converted back, and the original high-quality plate is never used again.
- **The viewer adds a second sRGB curve to EXR results.** CorridorKey's linear matte and its sRGB foreground both look wrong. The pixel probe shows 0–255 values after that extra conversion, not the real float values.
- **CorridorKey's "Input is Linear (EXR)" checkbox is a trap.** CorridorKey is always fed the sRGB JPEG copy, so ticking it (as the help text recommends) applies the linear conversion twice.
- **The OCIO node isn't real OCIO.** It offers four fixed names and loads no config file. It has no display/view transforms, no camera log inputs (LogC, S-Log3…), and it works on the 8-bit copies anyway. The "Rec709" option fails on every frame but reports success.

**What a studio needs:** keep the plate in float all the way through, use a real OCIO config (ACES roles, camera log inputs), and write proper linear EXRs back out.

---

## 3. Getting results out and into Nuke

### Roto → Nuke: the best part of the app ✅
- **Real Bezier shapes.** You paste a Roto node into Nuke and get proper Bezier shapes with tangents, sharp corners where they belong, animated feather, and names like `Shape_TopLeft_3`.
- **Keys are sparse and editable.** They're reduced to what's needed within about 1.5 pixels, not keyed on every frame.
- **The point count stays the same** through the shot, which is what makes clean-up in Nuke practical.
- **Keys use the plate's real frame numbers.**

**Things to watch:**
- **A reappearing object can lose points.** When it comes back after a gap, its shape can return with a different point count. The export then chops off the extra points (for example, 8 of 18 points kept), which kinks the shape.
- **Layers are merged.** RotoToShape looks for them in the wrong folder, so all SuperMatte layers become one shape set.
- **The Roto node doesn't set its format.** If the Nuke script's root format differs, the shapes may sit in the wrong place *(inferred)*.
- **Some studios block the export.** The shapes are built by Python that runs when the node is created *(inferred)*.
- **Shapes may not switch off when an object leaves frame.** The lifetime settings may use the wrong Nuke names, in which case vanished shapes stay frozen on screen *(needs checking in Nuke)*.

### Camera → Nuke: broken ❌
- **The file won't open:** it's written as one long line.
- **The export never runs:** the tracker and the exporter look in different folders.
- **The camera and point cloud don't line up.**
- **Keys start at frame 1,** not at your plate's first frame, and slip if the tracker skipped any frames.
- **Lens information is missing.** There's no lens distortion and no principal point, and the filmback is a guess.

### Unified Output: not trustworthy yet ❌
- **Inputs get mixed up.** It picks inputs by their *names*, not by your wires, so "Keyed RGBA", "Video Plate" and "Depth Map" can all end up holding **the same frames**.
- **The keyer's result never arrives.** CorridorKey's output is never passed on; you get the rough BiRefNet guide matte instead.
- **The 8-bit PNG option damages mattes.** A default gamma of 2.2 is applied to everything, including mattes and depth, so a 50% alpha becomes about 73% and edges look too solid.
- **"16-bit Float EXR" actually writes 32-bit.**
- **EXRs contain sRGB values stored as float,** so Nuke, which reads EXR as linear, shows them washed out.
- **Mattes come out as a single-channel image.** In Nuke they appear as luminance, not as `rgba.alpha`.
- **Missing output features:** there's no premultiply option, no multi-channel EXR (for example RGBA plus depth.Z), no shot or version naming, and no frame handles.

---

## 4. Tools for fixing a matte

### What you get
- **SuperMatte refinement:** trimap grow/shrink, fill holes, choke/expand, threshold/contrast, feather, and optional temporal smoothing.
- **Interactive prompts:** click to add, Shift-click to subtract, or draw a box, per frame and per layer, with keys shown on the timeline.
- **A text prompt** via GroundingDINO, for example "person".
- **Viewer modes:** source, matte, comp and 3D. There's a mask overlay, black/white/checkerboard backgrounds, an **A/B wipe** against the source, and a pixel probe.

### What's missing or broken
- **Your corrections on later frames are ignored** on plates numbered from 1001: only the first set of clicks is used. On video, corrections land one frame early.
- **Your points disappear after you save and reopen a project,** and clicking again can crash the timeline.
- **You can't delete a single point.** The only option is "clear all points on this frame", and clicks can't be undone.
- **Hiding a layer with the eye icon doesn't remove it from the render.**
- **Temporal Stabilization adds ghost edges.** It moves the previous frame's matte the wrong way, so it makes flicker worse.
- **4K hair is refined at 2K.** Anything over 2048 pixels is refined at 2048 and scaled up.
- **All mattes are 8-bit PNG,** so soft edges and motion blur can show banding.
- **No professional edge tools:** there's no core/edge split, hair detail control, edge colour or edge extend.
- **Viewer gaps:** no R/G/B/A channel view, no exposure or gamma slider, and no A/B between two different nodes.
- **Slow playback.** There's no RAM cache, frames are re-read from disk every time, and it always plays at 24 fps. Expect well below real time on 4K *(inferred)*.

---

## 5. Each AI tool, compared with what artists already use

### SuperMatte (SAM 1 / SAM 3 + ViTMatte / MEMatte / VideoMaMa)
- **SAM 1 and SAM 3 work on each frame on their own.** They don't remember the object between frames; your clicks are just carried forward by point tracking. Expect chattering edges and lost objects on longer shots, weaker than DaVinci Resolve's Magic Mask or proper SAM 2 video tracking.
- **SAM 2 (SAMURAI) crashes every time.** It is the only mode that does remember the object across frames, so the best option is the broken one.
- **The default ViTMatte refiner crashes on 1920×1080 plates,** and shifts the matte by up to about 16 pixels on 4K.
- **MEMatte is good for hair** when it gets a good trimap.
- **VideoMaMa** is based on Stable Video Diffusion and probably needs more than 16 GB of VRAM *(inferred from its authors' notes)*. It also squashes every plate to 1024×576 and keeps all frames in RAM.

**Verdict:** useful for temp and previs mattes today. Once SAMURAI and the frame-number bugs are fixed, it could be a real first-pass roto helper.

### CorridorKey (AI green/blue-screen keyer)
- **The underlying model is excellent.** It gives a clean foreground, a linear matte and premultiplied RGBA, saved as half-float EXR.
- **The way the app uses it lets it down:**
  - It keys the **JPEG copy** of the plate.
  - **Eight of its 16 settings do nothing:** expansion, feather, anti-flicker, sensor noise, output mode, custom BG and others.
  - **Red screen crashes it.** Blue screen needs an internet download.
  - **Its result doesn't reach the output node.**
- **Handy bonus:** with no guide mask, it makes one automatically with BiRefNet.

**Verdict:** worth using as a first pass on hard hair shots, alongside Keylight or IBK, as long as you take the EXRs straight from its cache folder.

### Depth (Depth Anything V2)
- **Each frame is estimated separately.** It uses the single-image model, not the video version.
- **It flickers ("pumping").** Each frame is normalised on its own, so values shift as objects enter or leave frame.
- **Output is 8-bit PNG,** which bands badly in ZDefocus or fog.
- **Picking a preview colour map ruins the output.** Choosing "Turbo" writes coloured images instead of depth data.
- **Frames are numbered from 0,** not from your plate's first frame.
- **Depth is relative, not real distance.** The real-distance ("metric") version is included in the code but never used.

**Verdict:** OK as a rough fog or haze mask. Not usable for depth-of-field until it writes float, stays stable over time and keeps frame numbers.

### 3D Tracker (COLMAP / GLOMAP)
- **It's photogrammetry-style tracking,** not a matchmove tracker like SynthEyes, 3DEqualizer or Nuke's CameraTracker.
- **It can't run on any machine yet.** The COLMAP and GLOMAP programs it needs aren't included or downloaded.
- **"SuperPoint AI" doesn't exist.** Choosing it quietly uses the standard method (SIFT) on the CPU instead.
- **It doesn't mask moving objects,** even though your SuperMatte mattes could do this with one setting.
- **The export is broken** (see section 3).

**Verdict:** not usable for matchmove yet.

### RotoToShape (matte → Nuke Roto)
- **The most promising tool in the app.** Points are placed where the curve bends most, snapped to the edge, tracked with optical flow, smoothed and keyframe-reduced.

**Verdict:** a real time-saver for first-pass roto that you then clean up in Nuke.

### AI Roto (body-pose shapes)
- **Only one person.** It uses MediaPipe body tracking.
- **Its depth logic is backwards.** It hides limbs that are *in front*, and it compares 0–255 values against 0–1 thresholds.
- **Its "Depth Map" input actually receives the plate.** Depth frames numbered from 0 also don't match plates numbered from 1001.
- **When its inputs are missing, the node still shows as successful.**

**Verdict:** not reliable yet.

---

## 6. Speed and hardware (16 GB card)

*These are estimates from what's known about the models, not measured on this machine.*

| Tool | Likely VRAM | Fits on 16 GB? |
|---|---|---|
| SAM ViT-H | ~6–8 GB | ✅ |
| SAM 2.1 Large (SAMURAI, once fixed) | fits HD and 4K | ✅ |
| ViTMatte at 2048 | ~6–10 GB | ✅ |
| CorridorKey at 2048 | ~10 GB | ✅ |
| Depth Anything V2 Large | ~3–4 GB | ✅ |
| VideoMaMa | 24 GB+ | ❌ likely out of memory |

- **Two models can be loaded at once.** SAM runs in its own process while ViTMatte loads inside the app.
- **The VRAM readout in the footer never shows,** because a needed package is missing. Even if it did, it would ignore the SAM process.
- **SAM reloads before every node,** because the AI process is restarted between nodes, which costs time.
- **There is a render queue** (right-click → Add to Render Queue), but:
  - it gets stuck if a node fails or is stopped;
  - it only works within one project, so you can't queue different shots;
  - there's no command-line or farm mode;
  - progress is a percentage only, with no time remaining or frames per second.

---

## 7. Everyday use and trust

- **Undo:** covers adding, deleting, moving and connecting nodes, and sliders. It doesn't cover clicks, layers, drop-downs, checkboxes or text boxes. **Undo after deleting a node can crash the app.**
- **Errors:** they show in each node's console with a copy button, which is good. Errors from the AI engine say "check terminal", but there is no visible terminal.
- **Missing models:** the app checks at start-up, which is good.
- **Saving:**
  - There's no autosave and no "save changes?" prompt on close.
  - "Save As" under a new name loses your previous renders.
  - Projects containing a Dot node can't be saved at all.
- **Help text doesn't match the app.** It promises MatAnyone 2 (not included), red screen, SuperPoint, working CorridorKey settings, and "hair, fur and motion blur" quality.
- **Keyboard shortcuts:**
  - **Nuke-like:** Tab search (currently broken), D to disable, Left/Right to step frames, I/O for In/Out, and F to fit.
  - **Missing:** Space or L to play, channel keys, Ctrl-drag sampling, and typing exact values into sliders.
  - **Keys 1–9 all do the same thing.**

---

## 8. What a studio would expect that's missing

- The plate kept in **float** from start to finish
- A real **OCIO config** with ACES and camera log support
- **Multi-channel RGBA EXR** output (with depth.Z), and a premultiply switch
- **Frame handles,** real frame rate and pixel aspect
- **Shot and version naming,** and publishing to a shot folder
- **A command-line and batch mode** for farms or overnight runs, with a queue across shots
- **A Read/Write template** for Nuke alongside the roto and camera, and **lens distortion** export
- **A sidecar file** recording which model, settings and version made each output
- **Tests** that check the Nuke exports open correctly

---

## 9. Top 5 strengths
1. **Roto → Nuke export:** real editable Bezier shapes with feather, sensible keys and real frame numbers.
2. **A strong set of models** in one graph: SAM 1/2/3, ViTMatte, MEMatte, CorridorKey, BiRefNet, Depth Anything and COLMAP.
3. **Smart caching, Freeze and Bypass,** so you can tweak settings without re-running the whole chain (Freeze needs fixing first).
4. **Interactive clicking and boxes per frame and per layer,** with a live SAM preview and text prompts.
5. **Solid viewer basics:** A/B wipe, checkerboard, matte view, pixel probe and Nuke-style navigation.

## 10. Top 10 improvements, ranked by impact for artists
1. **Stop throwing the plate away.** Work from a float (or at least 16-bit PNG) copy with no JPEG, handle DPX, log and ACES through a real OCIO config, and write proper linear EXRs.
2. **Wire inputs by the actual connection,** and let CorridorKey's key reach the output.
3. **Fix the camera export:** line breaks, folder, axis flip, real frame numbers and lens distortion.
4. **Fix SAMURAI** and make it the default, since it's the only mode that remembers the object across frames.
5. **Fix click corrections:** frame numbers, points surviving save/reload, and undo for clicks. Make the layer eye icon work.
6. **Make In/Out and frame ranges real** in every tool, with handles.
7. **Better mattes:** 16-bit or float output, full-resolution refinement at 4K, and core/edge and edge-extend controls. Crop the ViTMatte padding so HD works.
8. **Remove options that do nothing** (8 CorridorKey settings, red screen, SuperPoint). Stop the depth colour map being baked into the output, and stop gamma being applied to mattes.
9. **Better depth:** float EXR, stable across the shot (or the video depth model), a real-distance option, and 1001 numbering.
10. **Production basics:** command-line and batch mode, a queue that doesn't get stuck, time remaining, visible AI engine errors, keeping renders on Save As, and masking moving objects in the tracker.

---

## Final verdict

**Today** a comp artist would get the most value from the **Roto → Nuke export** on HD plates, plus **CorridorKey** used straight from its cache folder. Everything that depends on accurate colour or on delivery back to Nuke needs work first. That includes EXR output, the camera export, depth for defocus and multi-shot work.

**After the first five improvements above,** it would be a credible AI prep tool to run next to Nuke. It would save real time on first-pass roto, keys and mattes that an artist then finishes by hand, which is exactly how AI tools are being used in studios right now.
