import os

from utvfx.bridge.base_worker import BaseWorker
from utvfx.core.plate import Cancelled, Plate


class MediaWorker(BaseWorker):
    """
    Decodes the plate once and builds the 16-bit working tier that the viewer and
    downstream nodes read. Other tiers (fast JPG, float master) are built on demand
    by the nodes that need them; see utvfx.core.plate.
    """

    def __init__(self, node_id, params, inputs, cache_dir, output_dir, parent=None):
        super().__init__(node_id, params, inputs, cache_dir, output_dir, parent)
        self.plate_file = params.get("plate_file", "")
        self.is_sequence = params.get("is_sequence", True)
        self.colourspace = params.get("colourspace", "Auto")
        self.first_frame = int(params.get("first_frame", 1) or 1)
        self.working_scale = 0.5 if str(params.get("working_resolution", "Full")).startswith("Half") else 1.0

    def cancel(self):
        self.is_cancelled = True

    def run_task(self):
        if not self.plate_file or not os.path.exists(self.plate_file):
            raise FileNotFoundError("Media Plate has no valid file selected.")

        plate = Plate.prepare(self.plate_file, self.cache_dir, self.is_sequence, self.colourspace,
                              first_frame=self.first_frame, working_scale=self.working_scale)
        first, last = plate.frame_numbers[0], plate.frame_numbers[-1]
        aspect = plate.m.get("pixel_aspect", 1.0)
        self.log_message.emit(
            self.node_id,
            f"{os.path.basename(self.plate_file)}: {len(plate)} frames ({first}-{last}), "
            f"{plate.m['width']}x{plate.m['height']}"
            + (f" (pixel aspect {aspect:g}, anamorphic)" if abs(aspect - 1.0) > 1e-3 else "")
            + f", {plate.m['fps']:.3f} fps, colour space {plate.colourspace}"
            + (" — half-resolution working copy" if self.working_scale < 1 else ""),
        )

        if plate.has("png16"):
            self.log_message.emit(self.node_id, "Working copy is up to date.")
            self.progress_update.emit(self.node_id, 100, 100)
            return

        try:
            plate.ensure(
                "png16",
                progress=lambda done, total: self.progress_update.emit(self.node_id, int(done * 100 / total), 100),
                cancelled=lambda: self.is_cancelled,
            )
        except Cancelled:
            self.log_message.emit(self.node_id, "Media pre-processing cancelled.")
            return
        self.log_message.emit(self.node_id, "Working copy (16-bit) ready.")
