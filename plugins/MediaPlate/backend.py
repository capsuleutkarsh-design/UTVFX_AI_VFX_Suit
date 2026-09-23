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

    def cancel(self):
        self.is_cancelled = True

    def run_task(self):
        if not self.plate_file or not os.path.exists(self.plate_file):
            raise FileNotFoundError("Media Plate has no valid file selected.")

        plate = Plate.prepare(self.plate_file, self.cache_dir, self.is_sequence, self.colourspace)
        first, last = plate.frame_numbers[0], plate.frame_numbers[-1]
        self.log_message.emit(
            self.node_id,
            f"{os.path.basename(self.plate_file)}: {len(plate)} frames ({first}-{last}), "
            f"{plate.m['width']}x{plate.m['height']}, {plate.m['fps']:.3f} fps, colour space {plate.colourspace}",
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
