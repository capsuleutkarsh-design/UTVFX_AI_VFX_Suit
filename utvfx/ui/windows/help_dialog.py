from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QTextBrowser, QPushButton, QLabel, QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor

from utvfx.core.data_model import NODES_REGISTRY
from utvfx.ui import brand, icons, theme
from utvfx.version import APP_NAME, VERSION

# Expanded, professional documentation for all known nodes
NODE_HELP_DATA = {
    "media_plate": {
        "description": "The <b>Media Plate</b> node brings in footage: an image sequence (EXR, DPX, TIFF, PNG...) or a video file. It keeps the original colour for the final output and makes a display copy (16-bit PNG, plus JPG where a node needs it) that the AI nodes and the viewer use. Frames keep their original numbers.",
        "params": {
            "plate_file": "The first frame of an image sequence, or a video file.",
            "is_sequence": "Load every numbered frame next to the chosen file as one sequence.",
            "first_frame": "The frame number a video starts at (image sequences keep their own numbers). 1001 is the usual VFX start.",
            "working_resolution": "Half makes the AI nodes and the viewer work at half size, much faster on 4K plates. The original stays full size for the output.",
            "colourspace": "The colour space of the footage. Auto reads it from the file (EXR chromaticities, video tags); set it by hand for log footage such as LogC or S-Log3."
        }
    },
    "grade": {
        "description": "The <b>Grade</b> node is Nuke's Grade: it works in scene-linear ACEScg on the full-quality frames (highlights above 1 are kept) and never changes alpha. The result is a new plate, so AI nodes after it see the graded picture and the Output node gets the graded EXRs.",
        "params": {
            "blackpoint": "This input value becomes black (0).",
            "whitepoint": "This input value becomes white (1).",
            "lift": "Raises or lowers the blacks while white stays where it is.",
            "gain": "Scales the whites while black stays where it is.",
            "multiply": "Multiplies every value (brightness in linear light).",
            "offset": "Adds a value to every pixel.",
            "gamma": "Bends the midtones; applied to positive values only.",
            "black_clamp": "Clamps results below 0, as Nuke does by default.",
            "white_clamp": "Clamps results above 1. This removes highlight detail.",
            "unpremult": "For premultiplied RGBA such as the keyer's output: grades the colour without darkening or brightening the soft edges."
        }
    },
    "ocio_colorspace": {
        "description": "The <b>OCIO ColorSpace</b> node converts pictures with the OpenColorIO config (the ACES studio config unless the OCIO variable names another). Its result is tagged with the new colour space, so the viewer shows it correctly and the Output node writes it as it is.",
        "params": {
            "in_space": "Auto uses the colour space the input is tagged with. Choosing one reinterprets the input's pixels, for footage that was tagged wrongly (for video, set it on the Media Plate).",
            "out_space": "The colour space to convert to, or a display with its view transform (ACES SDR Video or Un-tone-mapped) for display-referred deliveries."
        }
    },
    "ai_depth_estimator": {
        "description": "The <b>Depth</b> node uses Depth Anything V2 to predict a depth map for every frame of the plate. It writes one float EXR channel (Z) per frame, numbered like the plate, for ZDefocus, fog and depth-sorted roto. The viewer shows a separate preview picture.",
        "params": {
            "model_size": "Small is fastest; Large gives the most detailed depth and needs more VRAM.",
            "input_size": "The size the model works at. Larger values give sharper depth edges but take longer.",
            "depth_type": "Relative: 0-1 over the whole shot, the same range on every frame (no pumping). Metric: distance from the camera in metres, with the indoor (up to 20 m) or outdoor (up to 80 m) model.",
            "near_value": "For relative depth: whether near objects are 1 (Nuke ZDefocus 'far = 0') or 0.",
            "temporal_smoothing": "Blends each frame with the previous one, moved along the image motion, to calm flicker.",
            "blur_radius": "Softens the depth map (written into the EXR).",
            "gamma": "Contrast of the viewer preview only; the EXR is not changed.",
            "colormap": "Colours of the viewer preview only; the EXR is not changed."
        }
    },
    "composite_output": {
        "description": "The <b>Unified Output</b> node delivers everything for comp: the plate and keyed RGBA at full quality, mattes in the alpha channel and depth in Z (never colour-converted), the camera for Nuke, Blender and USD, and roto shapes. Files are named shot_layer.frame with the plate's frame numbers and follow the timeline's In/Out. A Nuke script with a Read for every layer and a JSON sidecar are written next to them.",
        "params": {
            "output_dir": "Where to write. Blank uses the project's output folder from Settings.",
            "shot_name": "Used in every file name. Blank uses the project name.",
            "file_format": "EXR keeps the full range (half float is standard for comp; full float for data-heavy work). PNG is display-referred, for review.",
            "exr_colourspace": "Colour space of the plate and keyed RGBA in EXR files. ACEScg matches the app's working space.",
            "png_display": "The view transform used for PNG files.",
            "combine_exr": "Also writes one EXR per frame with R, G, B, A and depth.Z together.",
            "premultiply": "When the combined EXR takes its colour from the plate and its alpha from the matte, multiply the colour by the alpha.",
            "split_core_edge": "Also writes the matte's solid core and its soft edge as separate mattes.",
            "write_nuke_reads": "Writes shot_reads.nk with a Read node for every layer; mattes and depth are read raw.",
            "export_camera": "Writes the 3D Tracker's camera for Nuke (.nk and .chan), Blender, USD (if installed) and a PLY point cloud.",
            "scene_scale": "Multiplies the whole scene. COLMAP's units are arbitrary; set this so a known distance comes out right.",
            "level_ground": "Rotates the scene so the ground found in the point cloud is level.",
            "write_undistort": "Writes STMaps (undistort and redistort) and an undistorted plate for the solved lens.",
            "overscan": "Extra border around the undistorted plate so the barrel's corners are not cut (0.1 = 10%).",
            "blender_exe": "Path to blender.exe. When set, the camera is also baked to Alembic (.abc) and a .blend.",
            "export_roto_nuke": "Writes shot_roto.nk: paste it into Nuke (Ctrl+V) and a Roto node builds the animated shapes from Roto to Shape or AI Roto, one Nuke layer per matte layer, each shape visible only on the frames it was found.",
            "roto_interpolation": "How the roto shapes move between keyframes in Nuke."
        }
    },
    "roto_to_shape": {
        "description": "The <b>Roto to Shape</b> node traces mattes (such as SuperMatte's, one set of shapes per layer) into Nuke roto shapes. A shape keeps its name and point count from frame to frame, so Nuke can animate it.",
        "params": {
            "point_mode": "Auto spaces points along the outline (more on curves); Fixed gives every shape the same number of points.",
            "auto_point_spacing": "Auto mode: roughly how many pixels apart points are. Lower gives more points.",
            "target_points": "Fixed mode: the number of points in each shape.",
            "curvature_weight": "How strongly points gather on curves rather than straight edges.",
            "corner_threshold": "Turns sharper than this become cusps; gentler ones stay smooth.",
            "simplify_epsilon": "Higher values give smoother, simpler outlines; lower values follow the matte more closely.",
            "edge_snap_radius": "How far points may move to sit exactly on the matte edge.",
            "min_area": "Ignores pieces of matte smaller than this many square pixels.",
            "edge_placement": "Where the outline sits on a soft edge: 0 = outer edge, 100 = solid core.",
            "generate_feather": "Also traces the soft edge and exports it as Nuke feather points.",
            "iou_threshold": "How much a shape must overlap the previous frame's shape to count as the same shape.",
            "include_holes": "Also trace holes inside the matte (for example between an arm and the body).",
            "max_missing_frames": "How many frames a shape may disappear for and still come back under the same name.",
            "temporal_smoothing": "Averages each shape with the frames either side to calm jitter.",
            "first_frame": "First plate frame to trace (0 = start).",
            "last_frame": "Last plate frame to trace (0 = end)."
        }
    },
    "corridor_keyer": {
        "description": "The <b>Corridor Keyer</b> keys green and blue screens with the CorridorKey network, guided by a rough matte (wire SuperMatte, or leave it empty and BiRefNet makes one). It writes a straight foreground, the matte and a premultiplied RGBA as linear EXRs, plus a preview comp.",
        "params": {
            "screen_color": "Auto detects green or blue; pick one if it guesses wrong. Blue uses the dedicated blue-screen weights.",
            "despill_strength": "How strongly the screen colour is removed from the subject.",
            "despill_limit_mode": "Average suits most shots; Max removes less and keeps saturated costumes safer.",
            "clean_islands": "Removes small floating specks from the matte.",
            "despeckle_thresh": "The largest speck, in pixels, that Clean Islands removes.",
            "mask_expansion": "Grows (positive) or shrinks (negative) the guide matte before keying, in pixels.",
            "despeckle_blur": "A median filter on the finished matte: removes pin-holes and specks without softening edges.",
            "feather_radius": "Softens the finished matte, in pixels.",
            "detail_intensity": "How much fine edge detail (hair) the refiner adds.",
            "temporal_anti_flicker": "Blends each matte with the previous one, moved along the image motion.",
            "sensor_noise": "Denoises the plate before keying (the output foreground is not denoised).",
            "foreground_output": "What the next node receives: premultiplied RGBA, or the straight foreground.",
            "input_linear": "Keys the scene-linear plate (EXR or log sources) instead of the display copy.",
            "custom_bg": "An image to put behind the preview comp. The EXRs are not affected.",
            "proc_res": "The size the network works at. 2048 is a good balance; 4096 needs much more VRAM."
        }
    },
    "ai_roto": {
        "description": "The <b>AI Roto</b> node finds the person's skeleton (MediaPipe Pose) and cuts their matte into Nuke-ready shapes per body part: head, torso, upper and lower arms and legs. With a depth map wired, a limb that passes behind the torso fades out and comes back when it is in front again.",
        "params": {
            "target_points_limb": "Points in each limb shape (the same on every frame, so Nuke can animate them).",
            "target_points_torso": "Points in the torso shape.",
            "target_points_head": "Points in the head shape.",
            "corner_threshold": "Turns sharper than this become cusps; gentler ones stay smooth.",
            "edge_snap_radius": "How far points may move to sit exactly on the matte edge.",
            "temporal_smoothing": "Averages each shape with the frames either side to calm jitter.",
            "hysteresis_high": "A limb fades out when it is more than this far behind the torso (0.08 = 8% of the torso's distance from camera).",
            "hysteresis_low": "A hidden limb shows again when it is less than this far behind the torso.",
            "flow_decay": "When the skeleton is lost, how quickly shapes stop following the image motion and hold the last pose.",
            "first_frame": "First plate frame to process (0 = start).",
            "last_frame": "Last plate frame to process (0 = end)."
        }
    },
    "sfm_tracker": {
        "description": "The <b>3D Camera Tracker</b> solves the camera move and a point cloud with COLMAP 4.2, using the same pipeline as the Automated Tracker. Wire a matte of moving objects (people, cars) into Moving Objects Matte so they don't steer the camera. Frames keep their plate numbers; squeezed plates are de-squeezed first.",
        "params": {
            "preset": "A starting point for a type of camera move, taken from the Automated Tracker: Handheld/Walking, Long shot, Drone/Orbit, Slow motion, Fast action, Action cam/Fisheye, 360 VR. It sets the solver, lens model and the thresholds below; change any of them and the preset shows Custom.",
            "solver": "Incremental adds frames one by one: the most reliable (the Automated Tracker's default). Global (GLOMAP) solves all frames at once: fast. Hierarchical splits a long shot into clusters and merges them. Whichever you pick, the incremental mapper tries again with looser settings if under 90% of frames solve.",
            "tri_angle": "Parallax the first pair of frames must show before the solve starts. Lower for walking and dolly shots, higher for orbits.",
            "inliers": "How many checked matches the first pair of frames needs. Higher is stricter.",
            "forward_motion": "How much a starting pair may move straight forward. 1.0 allows walk-forward shots, which COLMAP otherwise rejects.",
            "frame_step": "1 solves every frame. 2 solves every second frame, which widens the baseline on slow moves; the camera is keyed on the solved frames.",
            "single_camera": "One lens for the whole shot. Turn off for zooms: each frame then gets its own focal length (the exported camera uses the first frame's lens).",
            "gpu_features": "Find and match features on the GPU (much faster). Turn off only if the GPU runs out of memory.",
            "gpu_ba": "Run bundle adjustment on the GPU. Turn off to solve on the CPU.",
            "environment_mesh": "Also mesh the point cloud into a rough surface (environment_mesh.ply) for shadows, collisions or placing CG. It goes into the camera export.",
            "features": "SIFT is fastest. LightGlue matches more reliably. ALIKED + LightGlue (AI) copes better with blur, low texture and lighting changes. LoMa is the strongest and slowest.",
            "max_features": "Most points found per frame. More gives a denser cloud and a sturdier solve, but takes longer.",
            "max_image_size": "Frames larger than this are scaled down for finding features.",
            "camera_model": "Lens model to solve. SIMPLE_RADIAL suits most lenses; OPENCV for strong distortion; OPENCV_FISHEYE for fisheye; PINHOLE for undistorted plates.",
            "focal_mm": "The lens used, if known (from the camera report). The solve starts from it, which helps shots with little camera movement. 0 = let COLMAP estimate it.",
            "sensor_width_mm": "Width of the recorded image on the sensor, in mm (Super 35 is about 24.9, full frame 36). Only used with a known focal length.",
            "refine_lens": "Let the solve adjust focal length and distortion. Turn off only if the lens is known exactly.",
            "overlap": "How many neighbouring frames each frame is matched with.",
            "loop_detection": "Also matches frames that revisit the same view later in the shot (SIFT only).",
            "mask_grow": "Grows the moving-objects matte so features on its edges are ignored too.",
            "min_coverage": "The solve fails if fewer than this share of frames get a camera."
        }
    },
    "super_matte": {
        "description": "The <b>Super Matte</b> node uses Meta's Segment Anything Model (SAM) combined with ViTMatte to automatically generate pixel-perfect alpha mattes. You can prompt it with text, or click/box select regions, and it will refine the edges to handle hair, fur, and motion blur.",
        "params": {
            "sam_version": "Choose the underlying Segment Anything Model. SAMURAI provides better temporal tracking, while ViT-H provides the best single-frame quality.",
            "refiner_model": "The matting refiner to use after SAM creates the rough trimap.",
            "text_prompt": "Optional text prompt to automatically find the object using GroundingDINO (e.g., 'a person wearing a red jacket').",
            "tool_mode": "Whether to use Point clicks or Bounding Box for manual selection.",
            "bg_color": "The background color to composite against when previewing the alpha channel.",
            "mask_layers": "Manage multiple distinct masks inside one node.",
            "trimap_dilate": "How much to expand the rough mask to create the 'unknown' region for the matting algorithm. Increase if edge details (like hair) are being cut off.",
            "trimap_erode": "How much to shrink the inner solid mask. Increase if background pixels are being included in the solid foreground.",
            "fill_holes": "Automatically fill small holes inside the generated mask.",
            "feathering": "Apply a post-process Gaussian blur to the final alpha edge to soften it.",
            "shrink_grow": "Erode (negative) or dilate (positive) the final alpha matte globally.",
            "threshold": "Clip the alpha values. 128 means the midpoint.",
            "contrast": "Increase the contrast of the alpha channel to make semi-transparent pixels either fully opaque or transparent.",
            "temporal_smoothing": "Enable optical flow-based stabilization across multiple frames to reduce edge flickering."
        }
    },
    "dot_node": {
        "description": "The <b>Dot Node</b> is a simple pass-through dot used exclusively to organize your node graph and route messy wires neatly.",
        "params": {}
    }
}

def _manual_css():
    """Default stylesheet for the manual's HTML, built from theme tokens."""
    return f"""
        body {{ color: {theme.TEXT}; font-family: "{theme.FONT_FAMILY}"; font-size: 9pt; }}
        h1 {{ color: {theme.TEXT}; font-size: 14pt; font-weight: 600; margin: 0; }}
        p.h2 {{ color: {theme.TEXT}; font-size: 10pt; font-weight: 600; margin-top: 18px; margin-bottom: 6px; }}
        p {{ margin-top: 0; margin-bottom: 6px; }}
        b {{ color: {theme.TEXT}; font-weight: 600; }}
        .category {{ color: {theme.TEXT_DIM}; }}
        .dim {{ color: {theme.TEXT_DIM}; }}
        .faint {{ color: {theme.TEXT_FAINT}; }}
        .mono {{ font-family: "{theme.FONT_MONO}", Consolas, monospace; font-size: 8pt; color: {theme.TEXT_DIM}; }}
        .pname {{ color: {theme.TEXT}; font-weight: 600; }}
        td.param {{ padding: 6px 8px; }}
    """


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} user manual")
        self.resize(1000, 700)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 12)
        main_layout.setSpacing(8)

        # Header: logo on the left, what this window is on the right
        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(brand.logo_pixmap(28))
        logo.setToolTip(f"{APP_NAME} {VERSION}")
        header.addWidget(logo)
        header.addStretch()
        header.addWidget(theme.set_role(QLabel(f"User manual  ·  version {VERSION}"), "dim"))
        main_layout.addLayout(header)

        # Splitter
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Left panel (tree)
        self.node_tree = QTreeWidget()
        self.node_tree.setHeaderHidden(True)
        self.node_tree.setMinimumWidth(220)
        self.node_tree.setMaximumWidth(320)
        self.node_tree.setIndentation(12)
        self.node_tree.setIconSize(icons.ICON_SIZE)
        self.node_tree.currentItemChanged.connect(self.on_node_selected)

        # Right panel (browser); PanelBody gives it the panel grey behind the text
        self.text_browser = QTextBrowser()
        self.text_browser.setObjectName("PanelBody")
        self.text_browser.setOpenExternalLinks(True)
        self.text_browser.document().setDefaultStyleSheet(_manual_css())
        self.text_browser.document().setDocumentMargin(16)

        self.splitter.addWidget(self.node_tree)
        self.splitter.addWidget(self.text_browser)
        self.splitter.setSizes([260, 740])

        main_layout.addWidget(self.splitter)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_close = QPushButton("Close")
        theme.set_role(self.btn_close, "primary")
        self.btn_close.setDefault(True)
        self.btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_close)
        main_layout.addLayout(btn_layout)

        self.populate_nodes()

    def populate_nodes(self):
        # Group nodes by category
        categories = {}
        for ptype, data in NODES_REGISTRY.items():
            cat = data.get("category", "Uncategorized")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append((ptype, data))

        first_child = None
        header_font = theme.ui_font(weight=QFont.Weight.DemiBold)

        # Sort categories
        for cat in sorted(categories.keys()):
            # Top-level item (category header)
            cat_item = QTreeWidgetItem(self.node_tree)
            cat_item.setText(0, cat)
            cat_item.setFont(0, header_font)
            cat_item.setForeground(0, QColor(theme.TEXT_DIM))
            cat_item.setFlags(Qt.ItemIsEnabled) # Prevent selection, just expand/collapse

            # Nodes in category
            nodes = sorted(categories[cat], key=lambda x: x[1].get("name", x[0]))
            for ptype, data in nodes:
                node_item = QTreeWidgetItem(cat_item)
                node_item.setText(0, data.get('name', ptype))
                node_item.setIcon(0, icons.category_icon(ptype))
                node_item.setData(0, Qt.UserRole, ptype)

                if first_child is None:
                    first_child = node_item

            # Auto-expand all categories
            cat_item.setExpanded(True)

        # Select first actual node
        if first_child:
            self.node_tree.setCurrentItem(first_child)

    def on_node_selected(self, current, previous):
        if not current:
            return

        ptype = current.data(0, Qt.UserRole)
        if not ptype:
            # User clicked a category header somehow (though flags should prevent it)
            return

        node_data = NODES_REGISTRY.get(ptype, {})
        help_data = NODE_HELP_DATA.get(ptype, {})

        name = node_data.get("name", ptype)
        cat = node_data.get("category", "Node")
        color = theme.node_colour(ptype)

        desc = help_data.get("description", "<p>No documentation provided for this node yet.</p>")

        html = f"""
        <table width="100%" cellspacing="0" cellpadding="0"><tr>
            <td width="4" bgcolor="{color}"></td>
            <td style="padding-left: 10px;">
                <h1>{name}</h1>
                <span class="category">{cat}</span>&nbsp;&nbsp;<span class="mono">{ptype}</span>
            </td>
        </tr></table>
        <p style="margin-top: 12px;">{desc}</p>
        """

        # Inputs and outputs
        inputs = node_data.get("inputs", [])
        outputs = node_data.get("outputs", [])

        if inputs or outputs:
            html += "<p class='h2'>Connections</p><table cellspacing='0' cellpadding='3'>"
            if inputs:
                html += f"<tr><td class='dim'>Inputs</td><td class='mono'>{', '.join(inputs)}</td></tr>"
            if outputs:
                html += f"<tr><td class='dim'>Outputs</td><td class='mono'>{', '.join(outputs)}</td></tr>"
            html += "</table>"

        # Parameters
        params = node_data.get("parameters", [])
        if params:
            html += "<p class='h2'>Parameters</p>"
            html += f"<table width='100%' cellspacing='0' cellpadding='0' style='border-collapse: collapse;'>"
            for i, p in enumerate(params):
                pid = p.get("id", "unknown")
                pname = p.get("name", pid)
                ptype_ui = p.get("type", "unknown")
                pdefault = p.get("value", "")

                # Help text for this parameter, if any
                p_desc = "No description available."
                if "params" in help_data and pid in help_data["params"]:
                    p_desc = help_data["params"][pid]

                row_bg = theme.BG_HEADER if i % 2 == 0 else theme.BG_PANEL
                html += f"""
                <tr><td class="param" bgcolor="{row_bg}">
                    <span class="pname">{pname}</span>&nbsp;&nbsp;<span class="mono">{pid}</span>&nbsp;&nbsp;<span class="faint">{ptype_ui}</span><br>
                    <span class="dim">{p_desc}</span><br>
                    <span class="faint">Default</span>&nbsp;&nbsp;<span class="mono">{pdefault}</span>
                </td></tr>
                """
            html += "</table>"
        else:
            html += "<p class='faint' style='margin-top: 14px;'>This node has no parameters in the properties panel.</p>"

        self.text_browser.setHtml(html)
