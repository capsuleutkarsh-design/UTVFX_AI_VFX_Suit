# Defines the node definitions, mimicking the React data.ts

NODES_REGISTRY = {
    "matte_anyone": {
        "name": "MatteAnyone 2",
        "plugin_type": "matte_anyone",
        "category": "🎭 Matte",
        "color": "#0ea5e9", # sky
        "inputs": ["Video Plate"],
        "outputs": ["Alpha Matte", "Edge Overlay"],
        "parameters": [
            # Tab: Main Settings
            {"id": "model_selection", "name": "Model Selection", "tab": "Main Settings", "type": "radio", "value": "MatAnyone 2", "options": ["MatAnyone 2", "MatAnyone"]},
            {"id": "bg_color", "name": "Background Color", "tab": "Main Settings", "type": "color", "value": "#6aff9b"},
            {"id": "mask_file", "name": "Guide Mask File", "tab": "Main Settings", "type": "file", "value": ""},
            {"id": "start_frame", "name": "Start Frame", "tab": "Main Settings", "type": "text", "value": "1"},
            {"id": "end_frame", "name": "End Frame", "tab": "Main Settings", "type": "text", "value": "0"},
            {"id": "prompt", "name": "Object Prompt / Guide", "tab": "Main Settings", "type": "text", "value": "actor foreground"},
            {"id": "use_depth_assistant", "name": "Use Depth Assistant", "tab": "Main Settings", "type": "checkbox", "value": False},
            {"id": "depth_tolerance", "name": "Depth Tolerance %", "tab": "Main Settings", "type": "slider", "value": 20, "min": 5, "max": 100, "step": 5},
            
            # Tab: Advanced Processing
            {"id": "erode_kernel", "name": "Erode Kernel Size", "tab": "Advanced Processing", "type": "slider", "value": 10, "min": 0, "max": 50, "step": 1},
            {"id": "dilate_kernel", "name": "Dilate Kernel Size", "tab": "Advanced Processing", "type": "slider", "value": 10, "min": 0, "max": 50, "step": 1},
            {"id": "fill_holes", "name": "Fill Holes (Close Mask)", "tab": "Advanced Processing", "type": "checkbox", "value": True},
            {"id": "warmup_frames", "name": "Warmup Frames", "tab": "Advanced Processing", "type": "slider", "value": 10, "min": 0, "max": 50, "step": 1},
            {"id": "refinement_passes", "name": "Matte Refinement Passes", "tab": "Advanced Processing", "type": "slider", "value": 3, "min": 1, "max": 10, "step": 1},
            {"id": "edge_feather", "name": "Edge Feathering (px)", "tab": "Advanced Processing", "type": "slider", "value": 1.5, "min": 0, "max": 10, "step": 0.1},
            {"id": "temporal_coherence", "name": "Temporal Frame Coherence", "tab": "Advanced Processing", "type": "slider", "value": 0.85, "min": 0.0, "max": 1.0, "step": 0.05},
            {"id": "cuda_accel", "name": "CUDA FP16 Acceleration", "tab": "Advanced Processing", "type": "checkbox", "value": True}
        ]
    },
    "corridor_keyer": {
        "name": "Corridor Keyer",
        "plugin_type": "corridor_keyer",
        "category": "🔑 Keying",
        "color": "#10b981", # emerald
        "inputs": ["Video Plate", "Alpha Matte"],
        "outputs": ["Keyed RGBA"],
        "parameters": [
            # Tab 1: Keying & Despill
            {"id": "screen_color", "name": "Screen Color", "tab": "Keying & Despill", "type": "select", "value": "green", "options": ["green", "blue", "red"]},
            {"id": "despill_strength", "name": "Despill Strength", "tab": "Keying & Despill", "type": "slider", "value": 0.5, "min": 0.0, "max": 1.0, "step": 0.01},
            {"id": "despill_limit_mode", "name": "Despill Limit Mode", "tab": "Keying & Despill", "type": "select", "value": "average", "options": ["average", "max"]},
            
            # Tab 2: Matte Polish
            {"id": "clean_islands", "name": "Clean Islands (Auto-Despeckle)", "tab": "Matte Polish", "type": "checkbox", "value": True},
            {"id": "despeckle_thresh", "name": "Despeckle Threshold", "tab": "Matte Polish", "type": "slider", "value": 400, "min": 0, "max": 1000, "step": 1},
            {"id": "mask_expansion", "name": "Mask Expansion", "tab": "Matte Polish", "type": "slider", "value": 25, "min": 0, "max": 50, "step": 1},
            {"id": "despeckle_blur", "name": "Despeckle Blur", "tab": "Matte Polish", "type": "slider", "value": 5, "min": 0, "max": 20, "step": 1},
            {"id": "feather_radius", "name": "Feather Radius", "tab": "Matte Polish", "type": "slider", "value": 0, "min": 0, "max": 20, "step": 1},
            {"id": "detail_intensity", "name": "Detail Intensity", "tab": "Matte Polish", "type": "slider", "value": 1, "min": 0, "max": 3, "step": 1},
            {"id": "temporal_anti_flicker", "name": "Temporal Anti-Flicker", "tab": "Matte Polish", "type": "slider", "value": 0.0, "min": 0.0, "max": 1.0, "step": 0.1},
            {"id": "sensor_noise", "name": "Sensor Noise Reduction (Chroma)", "tab": "Matte Polish", "type": "slider", "value": 0, "min": 0, "max": 20, "step": 1},
            
            # Tab 3: System / I/O
            {"id": "output_dir", "name": "Output Directory", "tab": "System / I/O", "type": "file", "value": "..\\outputs"},
            {"id": "foreground_output", "name": "Foreground Output", "tab": "System / I/O", "type": "radio", "value": "Straight RGB", "options": ["Straight RGB", "Premultiplied"]},
            {"id": "input_linear", "name": "Input is Linear (EXR)", "tab": "System / I/O", "type": "checkbox", "value": False},
            {"id": "custom_bg", "name": "Custom Background Preview", "tab": "System / I/O", "type": "file", "value": ""},
            {"id": "proc_res", "name": "Processing Resolution", "tab": "System / I/O", "type": "select", "value": "2048", "options": ["512", "1024", "2048", "4096"]}
        ]
    },
    "roto_to_shape": {
        "name": "Matte to Shape",
        "plugin_type": "roto_to_shape",
        "category": "🎭 Matte",
        "color": "#8b5cf6", # violet
        "inputs": ["Alpha Matte"],
        "outputs": ["Shape Data"],
        "parameters": [
            {"id": "target_points", "name": "Control Points (Resolution)", "type": "slider", "value": 100, "min": 10, "max": 500, "step": 10},
            {"id": "min_area", "name": "Minimum Area (px)", "type": "slider", "value": 100, "min": 0, "max": 10000, "step": 100},
            {"id": "simplify_epsilon", "name": "Simplify Curve Epsilon", "type": "slider", "value": 1.0, "min": 0.0, "max": 10.0, "step": 0.5}
        ]
    },
    "sfm_tracker": {
        "name": "3D Camera Tracker",
        "plugin_type": "sfm_tracker",
        "category": "📍 Tracking",
        "color": "#eab308", # yellow
        "inputs": ["Video Plate"],
        "outputs": ["3D Camera Path", "3D Sparse Points"],
        "parameters": [
            {"id": "mapper_engine", "name": "Mapping Engine", "type": "radio", "value": "GLOMAP (Fast)", "options": ["COLMAP (Incremental)", "GLOMAP (Fast)"]},
            {"id": "feature_type", "name": "Feature Extractor Algo", "type": "select", "value": "SIFT (GPU)", "options": ["SIFT (GPU)", "DSP-SIFT", "SuperPoint AI"]},
            {"id": "max_features", "name": "Max Features Per Frame", "type": "slider", "value": 2000, "min": 500, "max": 10000, "step": 500},
            {"id": "match_type", "name": "Vocab Tree Match Mode", "type": "select", "value": "Sequential", "options": ["Sequential", "Exhaustive", "Spatial Neighbors"]},
            {"id": "min_tri_angle", "name": "Min Triangulation Angle", "type": "slider", "value": 1.5, "min": 0.5, "max": 5.0, "step": 0.1},
            {"id": "ba_iterations", "name": "Bundle Adjuster Steps", "type": "slider", "value": 100, "min": 20, "max": 300, "step": 10}
        ]
    },

    "media_plate": {
        "name": "Media Plate",
        "plugin_type": "media_plate",
        "category": "🎬 Media",
        "color": "#64748b", # slate
        "inputs": [],
        "outputs": ["Video Plate"],
        "parameters": [
            {"id": "plate_file", "name": "Media File", "type": "file", "value": ""},
            {"id": "is_sequence", "name": "Load as Image Sequence", "type": "checkbox", "value": False}
        ]
    },
    "composite_output": {
        "name": "Unified Output",
        "plugin_type": "composite_output",
        "category": "📦 Output",
        "color": "#f43f5e", # rose
        "inputs": ["Keyed RGBA", "Alpha Matte", "Video Plate", "3D Camera Path", "3D Sparse Points", "Dense Depth Map", "Shape Data"],
        "outputs": ["Final Presentation", "Export Assets"],
        "parameters": [
            {"id": "output_dir", "name": "Output Directory", "type": "file", "value": "..\\outputs"},
            {"id": "gamma", "name": "Display LUT Gamma", "type": "slider", "value": 2.2, "min": 1.0, "max": 3.2, "step": 0.1},
            {"id": "bit_depth", "name": "Target Render Bitrate", "type": "select", "value": "16-bit Float EXR", "options": ["8-bit PNG", "16-bit Float EXR", "32-bit Float EXR"]},
            
            # 3D Exporter Settings
            {"id": "export_nuke", "name": "Export Nuke Script (.nk)", "tab": "3D Export", "type": "checkbox", "value": True},
            {"id": "export_blender", "name": "Export Blender Script (.py)", "tab": "3D Export", "type": "checkbox", "value": True},
            {"id": "scene_scale", "name": "Scene Scale Multiplier", "tab": "3D Export", "type": "slider", "value": 10.0, "min": 0.1, "max": 100.0, "step": 0.1}
        ]
    },
    "sam3_rotoscope": {
        "name": "SAM 3 Rotoscope",
        "plugin_type": "sam3_rotoscope",
        "category": "🎭 Matte",
        "color": "#ef4444", # red
        "inputs": ["Video Plate"],
        "outputs": ["Alpha Matte"],
        "parameters": [
            {"id": "text_prompt", "name": "Text Prompt (Optional)", "type": "text", "value": ""},
            {"id": "coherence", "name": "Tracking Coherence", "type": "slider", "value": 0.8, "min": 0.0, "max": 1.0, "step": 0.1},
            {"id": "multiplexing", "name": "Multi-Object Multiplexing", "type": "checkbox", "value": True}
        ]
    },
    "ai_depth_estimator": {
        "name": "Depth Anything V2",
        "plugin_type": "ai_depth_estimator",
        "category": "🌊 Depth",
        "color": "#8b5cf6", # violet
        "inputs": ["Video Plate"],
        "outputs": ["Dense Depth Map"],
        "parameters": [
            {"id": "model_size", "name": "Model Architecture", "type": "select", "value": "Small (vits)", "options": ["Small (vits)", "Base (vitb)", "Large (vitl)"]},
            {"id": "invert_depth", "name": "Invert Depth", "type": "checkbox", "value": False}
        ]
    }
}
