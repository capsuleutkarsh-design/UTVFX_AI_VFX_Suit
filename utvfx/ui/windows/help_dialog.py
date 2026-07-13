import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, 
    QTreeWidget, QTreeWidgetItem, QTextBrowser, QPushButton, QLabel, QSizePolicy
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QColor, QIcon

from utvfx.core.data_model import NODES_REGISTRY

# Expanded, professional documentation for all known nodes
NODE_HELP_DATA = {
    "media_plate": {
        "description": "The <b>Media Plate</b> node acts as the source for your image or sequence. It streams frames from disk into the VFX pipeline.",
        "params": {
            "plate_file": "The absolute path to the main image or the first frame of an image sequence.",
            "is_sequence": "Check this if the media file is part of a numbered image sequence (e.g. frame_0001.exr) to load it as video."
        }
    },
    "grade": {
        "description": "The <b>Grade</b> node allows you to perform basic linear color correction, similar to Nuke's Grade node.",
        "params": {
            "blackpoint": "Defines the darkest point of the image. Values below this are crushed to black.",
            "whitepoint": "Defines the brightest point of the image. Values above this are blown out to white.",
            "lift": "Lifts the dark areas, effectively changing the black level without affecting pure whites.",
            "gain": "Multiplies the entire image, brightening or darkening whites while anchoring blacks.",
            "multiply": "Scales the color values mathematically.",
            "offset": "Adds a constant value to all pixels, shifting the entire histogram.",
            "gamma": "Adjusts the midtones of the image via a power curve (non-linear)."
        }
    },
    "ocio_colorspace": {
        "description": "The <b>OCIO Colorspace</b> node handles color transforms using the OpenColorIO standard. Use it to correctly linearize inputs or convert for final display.",
        "params": {
            "in_space": "The color space of the incoming image (e.g., sRGB for standard JPEGs, linear for EXRs).",
            "out_space": "The target color space to convert the image into."
        }
    },
    "ai_depth_estimator": {
        "description": "The <b>AI Depth Estimator</b> node uses Depth Anything V2 to analyze a 2D image and predict a 3D depth map (Z-Depth). This is heavily used for atmospheric haze and simulated depth-of-field.",
        "params": {
            "model_size": "The size of the AI model. Small is fastest; Large provides the most detailed depth but requires heavy VRAM.",
            "input_size": "The maximum resolution to process. Larger values yield sharper depth edges but drastically slow down computation.",
            "temporal_smoothing": "Amount of blending between adjacent frames to prevent the depth map from flickering in video.",
            "gamma": "Adjust the contrast of the generated depth map.",
            "blur_radius": "A post-process blur to smooth out the depth gradients.",
            "colormap": "The false-color map used when viewing the depth visually. (Grayscale is usually needed if plugging into other math nodes).",
            "invert_depth": "Inverts the Z-depth (swaps near and far planes)."
        }
    },
    "composite_output": {
        "description": "The <b>Composite Output</b> node handles exporting the final result of your node graph to disk, or exporting camera and 3D data to external DCC software.",
        "params": {
            "output_dir": "The destination directory where the rendered image sequence or project data will be saved.",
            "gamma": "Bakes a gamma curve into the output. Leave at 1.0 for linear output formats like EXR.",
            "bit_depth": "The output precision. Use 16-bit or 32-bit float for EXR to preserve high dynamic range.",
            "export_nuke": "Generates an automatic Nuke script (.nk) reproducing the 3D track, cameras, and compositing setup.",
            "export_blender": "Generates a Python script that builds the 3D tracking scene and cameras directly inside Blender.",
            "export_roto_nuke": "Exports AI-generated masks directly as Nuke Roto nodes with animated splines.",
            "scene_scale": "Scales the exported 3D scene (cameras, point clouds) to match the world scale of your 3D software."
        }
    },
    "roto_to_shape": {
        "description": "The <b>Roto to Shape</b> node converts pixel-based alpha masks (like the ones from Super Matte) into mathematical vector splines/polygons.",
        "params": {
            "target_points": "The target number of vertices for the generated vector polygon.",
            "min_area": "Removes any tiny isolated vector islands smaller than this area (in square pixels).",
            "simplify_epsilon": "The tolerance parameter for the Douglas-Peucker algorithm. Higher values result in fewer points and smoother curves, but lose tight details."
        }
    },
    "corridor_keyer": {
        "description": "The <b>Corridor Keyer</b> is a specialized matte extraction node designed for blue/green screens, offering aggressive spill suppression and auto-despeckling.",
        "params": {
            "screen_color": "Select whether the background you want to remove is green, blue, or red.",
            "despill_strength": "How aggressively to remove color cast from the background bouncing onto the foreground subject.",
            "despill_limit_mode": "The math operation used to calculate neutral limits during despill (average usually works best, max can be safer for saturated subjects).",
            "clean_islands": "Automatically deletes floating pixels (garbage) that shouldn't be part of the matte.",
            "despeckle_thresh": "The maximum size of the floating noise islands to aggressively remove.",
            "mask_expansion": "Dilates the generated mask to cover slight motion blur boundaries.",
            "despeckle_blur": "Softens the despeckled areas to avoid jagged edges on the matte.",
            "feather_radius": "Blurs the entire matte softly to blend the subject into the background.",
            "detail_intensity": "Recovers sharp edge details from the original plate that might have been lost in the heavy key.",
            "temporal_anti_flicker": "Reduces edge chatter/boiling across frames using temporal analysis.",
            "sensor_noise": "Pre-blurs chroma noise in the image to prevent a grainy key.",
            "output_dir": "If saving the key independently, this specifies the output folder.",
            "foreground_output": "Whether to output a Straight RGB image (with a separate alpha) or Premultiplied RGB (rgb * alpha).",
            "input_linear": "Check this if the input EXR plate is in linear light. The node mathematically requires linear light to operate correctly.",
            "custom_bg": "Optionally load a background image specifically to preview the key in context.",
            "proc_res": "The maximum processing resolution."
        }
    },
    "sfm_tracker": {
        "description": "The <b>3D Camera Tracker</b> analyzes the motion of pixels in the 2D video and mathematically solves for the original 3D camera movement and point cloud using Structure-from-Motion (SfM).",
        "params": {
            "mapper_engine": "The internal solver architecture (e.g., COLMAP or GLOMAP).",
            "feature_type": "The algorithm used to find trackable points (SuperPoint uses deep learning, SIFT is traditional).",
            "max_features": "The absolute maximum number of points to track per frame. Higher means denser point clouds but drastically slower solve times.",
            "match_type": "How to link points between frames (Sequential is best for normal video, Exhaustive is only for completely random photo sets).",
            "min_tri_angle": "Filters out 3D points that have bad triangulation geometry, resulting in a cleaner point cloud.",
            "ba_iterations": "Number of Bundle Adjustment passes to refine the camera solve mathematically. More iterations equals less sliding."
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

class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("UTVFX User Manual & Node Documentation")
        self.resize(1100, 750)
        
        # We define a much cleaner, premium CSS style that specifically targets the QTreeWidget
        self.setStyleSheet("""
            QDialog {
                background-color: #09090b;
                color: #fafafa;
            }
            QTreeWidget {
                background-color: #121212;
                border: 1px solid #27272a;
                border-radius: 8px;
                padding: 5px;
                outline: none;
                font-family: 'Inter', sans-serif;
                font-size: 13px;
            }
            QTreeWidget::item {
                padding: 10px;
                border-radius: 4px;
                color: #a1a1aa;
                margin-bottom: 2px;
            }
            QTreeWidget::item:selected {
                background-color: #27272a;
                color: #f59e0b;
                font-weight: bold;
            }
            QTreeWidget::item:hover:!selected {
                background-color: #18181b;
            }
            /* Style for the category headers (Top Level Items) */
            QTreeWidget::item:has-children {
                background-color: transparent;
                color: #71717a;
                font-size: 11px;
                font-weight: bold;
                letter-spacing: 1px;
                text-transform: uppercase;
                padding-top: 15px;
                padding-bottom: 5px;
            }
            QTextBrowser {
                background-color: #121212;
                border: 1px solid #27272a;
                border-radius: 8px;
                padding: 30px;
                color: #e4e4e7;
                font-family: 'Inter', sans-serif;
                font-size: 14px;
            }
            QPushButton {
                background-color: #27272a;
                color: #fafafa;
                border: 1px solid #3f3f46;
                padding: 8px 20px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #f59e0b;
                color: #000000;
                border: 1px solid #f59e0b;
            }
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Header title
        header_lbl = QLabel("📖 User Manual")
        header_lbl.setStyleSheet("font-size: 20px; font-weight: bold; color: #f59e0b; font-family: 'Space Grotesk'; margin-bottom: 10px;")
        main_layout.addWidget(header_lbl)
        
        # Splitter
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # Left Panel (Tree)
        self.node_tree = QTreeWidget()
        self.node_tree.setHeaderHidden(True)
        self.node_tree.setMinimumWidth(280)
        self.node_tree.setMaximumWidth(350)
        self.node_tree.setIndentation(10) # Minimal indentation for clean look
        self.node_tree.currentItemChanged.connect(self.on_node_selected)
        
        # Right Panel (Browser)
        self.text_browser = QTextBrowser()
        self.text_browser.setOpenExternalLinks(True)
        
        self.splitter.addWidget(self.node_tree)
        self.splitter.addWidget(self.text_browser)
        self.splitter.setSizes([320, 780])
        
        main_layout.addWidget(self.splitter)
        
        # Bottom Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_close = QPushButton("Close Manual")
        self.btn_close.setCursor(Qt.PointingHandCursor)
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
        
        # Sort categories
        for cat in sorted(categories.keys()):
            # Create a Top-Level Item (Category Header)
            cat_item = QTreeWidgetItem(self.node_tree)
            cat_item.setText(0, cat)
            cat_item.setFlags(Qt.ItemIsEnabled) # Prevent selection, just expand/collapse
            
            # Nodes in category
            nodes = sorted(categories[cat], key=lambda x: x[1].get("name", x[0]))
            for ptype, data in nodes:
                node_item = QTreeWidgetItem(cat_item)
                # Add an icon-like bullet prefix for visual hierarchy
                node_item.setText(0, f"■  {data.get('name', ptype)}")
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
        cat = node_data.get("category", "VFX NODE")
        color = node_data.get("color", "#f59e0b")
        
        desc = help_data.get("description", "<p>No documentation provided for this node yet.</p>")
        
        html = f"""
        <h1 style="color: {color}; font-size: 28px; margin-bottom: 2px;">{name}</h1>
        <h3 style="color: #71717a; font-size: 14px; margin-top: 0px; margin-bottom: 20px;">{cat.upper()}</h3>
        
        <div style="font-size: 14px; color: #d4d4d8; line-height: 1.5;">
            {desc}
        </div>
        """
        
        # Display inputs/outputs
        inputs = node_data.get("inputs", [])
        outputs = node_data.get("outputs", [])
        
        if inputs or outputs:
            html += f"<hr style='border: 1px solid #27272a;'><h2 style='color: {color};'>Connections</h2><ul>"
            if inputs:
                html += f"<li style='color: #d4d4d8; font-size: 14px;'><b>Requires Inputs:</b> <span style='color: #a1a1aa;'>{', '.join(inputs)}</span></li>"
            if outputs:
                html += f"<li style='color: #d4d4d8; font-size: 14px;'><b>Generates Outputs:</b> <span style='color: #a1a1aa;'>{', '.join(outputs)}</span></li>"
            html += "</ul>"
            
        # Display Parameters
        params = node_data.get("parameters", [])
        if params:
            html += f"<hr style='border: 1px solid #27272a;'><h2 style='color: {color};'>Configurable Parameters</h2>"
            
            html += "<table width='100%' cellpadding='10' cellspacing='0'>"
            for p in params:
                pid = p.get("id", "unknown")
                pname = p.get("name", pid)
                ptype_ui = p.get("type", "unknown")
                pdefault = p.get("value", "")
                
                # Try to get help text for this specific parameter
                p_desc = "No description available."
                if "params" in help_data and pid in help_data["params"]:
                    p_desc = help_data["params"][pid]
                    
                html += f"""
                <tr>
                    <td style="border-left: 4px solid {color}; background-color: #18181b; padding: 15px; margin-bottom: 10px;">
                        <span style="font-size: 16px; font-weight: bold; color: #fafafa;">{pname}</span> 
                        <span style="font-size: 12px; color: #71717a;">[{ptype_ui.upper()}]</span>
                        <br><br>
                        <span style="font-size: 13px; color: #a1a1aa;">{p_desc}</span>
                        <br><br>
                        <span style="font-size: 13px; color: {color}; font-weight: bold;">Default Value: {pdefault}</span>
                    </td>
                </tr>
                <tr><td height="10"></td></tr>
                """
            html += "</table>"
        else:
            html += "<br><br><span style='color: #71717a; font-style: italic;'>This node has no configurable parameters in the Properties panel.</span>"
            
        self.text_browser.setHtml(html)
