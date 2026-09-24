"""Unified Output: everything the graph made, delivered for comp.

  <output>/<layer>/<shot>_<layer>.<frame>.exr   plate, keyed RGBA, mattes, depth (plate frame numbers)
  <output>/combined/...                          optional one multi-channel EXR per frame
  <output>/tracking/                             camera (camera.py)
  <output>/roto/                                 Nuke roto shapes
  <output>/<shot>_reads.nk                       a Read for every layer
  <output>/<shot>_export.json                    what was written, colour spaces and frame ranges
"""
import os
import shutil

from plugins.CompositeOutput.roto_exporter import export_roto_to_nuke
from utvfx.bridge.base_worker import BaseWorker


def safe_name(text):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in str(text)).strip("_") or "shot"


class CompositeOutputWorker(BaseWorker):
    def __init__(self, node_id, params, inputs, cache_dir, output_dir, parent=None):
        super().__init__(node_id, params, inputs, cache_dir, output_dir, parent)
        self.inputs = inputs
        self.rgba_path = inputs.get("Keyed RGBA")
        self.alpha_path = inputs.get("Alpha Matte")
        self.plate_path = inputs.get("Video Plate")
        self.depth_path = inputs.get("Dense Depth Map")
        self.tracking_path = inputs.get("3D Sparse Points") or inputs.get("3D Camera Path")
        self.shape_path = inputs.get("Shape Data")

        from utvfx.core.settings_manager import SettingsManager
        settings = SettingsManager()
        # An absolute folder on the node wins; otherwise the project's output folder from Settings.
        chosen = params.get("output_dir") or ""
        self.output_dir = chosen if os.path.isabs(chosen) else settings.get("output_dir")
        self.shot = safe_name(params.get("shot_name") or getattr(settings, "current_project_name", "shot"))

    def _exists(self, path):
        return bool(path) and os.path.isdir(str(path))

    def _frame_numbers(self):
        """Plate frame numbers inside the timeline's In/Out, taken from the first image layer wired."""
        from utvfx.core.image_nodes import Frames
        from utvfx.core.plate import find_sequence
        for path, colour_layer in ((self.plate_path, True), (self.rgba_path, True), (self.alpha_path, False),
                                   (self.depth_path, False)):
            if self._exists(path):
                sequence = Frames(path).sequence if colour_layer else find_sequence(path)
                if sequence:
                    return {sequence[i][0] for i in self.positions(len(sequence))}
        return None

    def run_task(self):
        from plugins.CompositeOutput import deliver
        from plugins.CompositeOutput.images import ImageExporter

        os.makedirs(self.output_dir, exist_ok=True)
        self.log_message.emit(self.node_id, f"Writing to {self.output_dir} as shot '{self.shot}'.")
        log = lambda text: self.log_message.emit(self.node_id, text)  # noqa: E731
        numbers = self._frame_numbers() if self.frame_range else None
        stage = {"n": 0}
        stages = sum(1 for p in (self.plate_path, self.rgba_path, self.alpha_path, self.depth_path) if self._exists(p))
        stages += bool(self.params.get("combine_exr")) + 1

        def progress(done, total):
            self.progress_update.emit(self.node_id, int(100 * (stage["n"] + done / max(total, 1)) / max(stages, 1)), 100)

        images = ImageExporter(self.output_dir, self.shot, self.params, numbers, log,
                               cancelled=lambda: self.is_cancelled, progress=progress)

        def step(fn, *args):
            if not self.is_cancelled:
                fn(*args)
                stage["n"] += 1

        if self._exists(self.plate_path):
            step(images.colour_layer, self.plate_path, "plate")
        if self._exists(self.rgba_path):
            step(images.colour_layer, self.rgba_path, "keyed")
        if self._exists(self.alpha_path):
            step(images.matte_layer, self.alpha_path, "matte", bool(self.params.get("split_core_edge", False)))
        if self._exists(self.depth_path):
            step(images.depth_layer, self.depth_path)
        if self.params.get("combine_exr", False):
            colour_source = self.rgba_path if self._exists(self.rgba_path) else self.plate_path
            if self._exists(colour_source):
                matte = None if colour_source == self.rgba_path else (self.alpha_path if self._exists(self.alpha_path) else None)
                step(images.combined, colour_source, matte, self.depth_path if self._exists(self.depth_path) else None,
                     bool(self.params.get("premultiply", True)))
            else:
                log("Combined EXR needs the plate or the keyed RGBA; skipped.")
        if self.is_cancelled:
            return

        camera = None
        if self._exists(self.tracking_path) and self.params.get("export_camera", True):
            import importlib
            from plugins.CompositeOutput.camera import export_camera
            log("Exporting the camera...")
            colmap_exe = importlib.import_module("plugins.3DTracker.backend").COLMAP_EXE
            camera = export_camera(self.tracking_path, self.output_dir, self.params, log, colmap_exe=colmap_exe)
            log(f"Camera: {camera['frames_count']} frames, {camera['points_count']} points -> "
                f"{len(camera['exported_files'])} files in tracking/.")

        roto = None
        if self._exists(self.shape_path) and self.params.get("export_roto_nuke", True):
            shapes_json = os.path.join(self.shape_path, "shapes.json")
            if os.path.isfile(shapes_json):
                roto_dir = os.path.join(self.output_dir, "roto")
                os.makedirs(roto_dir, exist_ok=True)
                roto = os.path.join(roto_dir, f"{self.shot}_roto.nk")
                dest_json = os.path.join(roto_dir, f"{self.shot}_shapes.json")
                shutil.copy2(shapes_json, dest_json)
                export_roto_to_nuke(dest_json, roto, self.params.get("roto_interpolation", "Linear"))
                log(f"Roto: {roto}")

        fps, size = None, (None, None)
        from utvfx.core.plate import plate_for_folder
        plate = plate_for_folder(self.plate_path) if self._exists(self.plate_path) else None
        if plate is not None:
            fps, size = plate.m.get("fps"), (plate.m.get("width"), plate.m.get("height"))
        if images.layers and self.params.get("write_nuke_reads", True):
            deliver.nuke_reads(os.path.join(self.output_dir, f"{self.shot}_reads.nk"), images.layers, fps, *size)
        deliver.sidecar(os.path.join(self.output_dir, f"{self.shot}_export.json"), self.shot, images.layers, {
            "fps": fps, "plate_size": list(size) if size[0] else None,
            "frame_range": [min(numbers), max(numbers)] if numbers else None,
            "camera": [os.path.relpath(p, self.output_dir) for p in camera["exported_files"]] if camera else None,
            "roto": os.path.relpath(roto, self.output_dir) if roto else None,
        })
        self.progress_update.emit(self.node_id, 100, 100)
        log("Unified Output complete.")
