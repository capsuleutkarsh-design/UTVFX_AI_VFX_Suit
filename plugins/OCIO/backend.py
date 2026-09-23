"""OCIO ColorSpace: convert with the app's OpenColorIO config (ACES studio config by default).

Input: Auto takes the colour space the input is tagged with; choosing one reinterprets
the input's pixels as that space (for footage that was tagged wrongly).
Output: any colour space of the config, or a display with its view transform (for
delivering display-referred files). The result is tagged with its colour space, so the
viewer and the next nodes read it correctly, and the Output node writes it as it is.
"""
import os
from concurrent.futures import ThreadPoolExecutor

import OpenImageIO as oiio

from utvfx.bridge.base_worker import BaseWorker
from utvfx.core import colour, image_nodes

# Names used by projects saved before the node read the OCIO config.
LEGACY = {"linear": colour.LINEAR_REC709, "sRGB": colour.SRGB, "Rec709": colour.REC709_VIDEO}
DISPLAY_PREFIX = "Display: "  # out_space options like "Display: sRGB - Display / ACES 1.0 - SDR Video"


def parse_output(value):
    """(colour space, None) or (display, view) for an out_space option."""
    if value.startswith(DISPLAY_PREFIX):
        display, view = value[len(DISPLAY_PREFIX):].split(" / ", 1)
        return display, view
    return value, None


def check_names(in_space, out_value):
    names = set(colour._config_names())
    if in_space != colour.AUTO and in_space not in names:
        raise Exception(f"'{in_space}' is not a colour space of the OCIO config.")
    target, view = parse_output(out_value)
    if view is None and target not in names:
        raise Exception(f"'{target}' is not a colour space of the OCIO config.")
    if view is not None:
        config = oiio.ColorConfig()
        if target not in config.getDisplayNames() or view not in config.getViewNames(target):
            raise Exception(f"'{target}' / '{view}' is not a display and view of the OCIO config.")


class OCIOWorker(BaseWorker):
    def run_task(self):
        in_space = LEGACY.get(self.params.get("in_space"), self.params.get("in_space", colour.AUTO))
        out_value = LEGACY.get(self.params.get("out_space"), self.params.get("out_space", colour.SCENE_LINEAR))
        check_names(in_space, out_value)
        target, view = parse_output(out_value)

        frames = image_nodes.Frames(self.inputs.get("Image"), cancelled=lambda: self.is_cancelled)
        if in_space != colour.AUTO and frames.decoded:
            raise Exception("A video plate is already decoded; set its colour space on the Media Plate instead.")
        # Reinterpreting: the input files' own pixel values are taken as in_space.
        source = frames.colourspace if in_space == colour.AUTO else in_space
        sequence = [frames.sequence[i] for i in self.positions(len(frames.sequence))]
        out = image_nodes.start_output(self.cache_dir)
        total = len(sequence)
        what = f"{target} ({view})" if view else target
        self.log_message.emit(self.node_id, f"Converting {total} frames: {source} -> {what}.")

        def work(item):
            number, path = item
            if self.is_cancelled:
                return
            rgb, alpha = frames.read(path, source)
            if view:
                rgb = colour._transform(rgb, lambda d, s: oiio.ImageBufAlgo.ociodisplay(
                    d, s, target, view, colour.SCENE_LINEAR))
            else:
                rgb = colour.convert(rgb, colour.SCENE_LINEAR, target)
            image_nodes.write_frame(out, number, rgb, alpha, target)

        done = 0
        with ThreadPoolExecutor(max(2, min(6, (os.cpu_count() or 4) - 2))) as pool:
            for _ in pool.map(work, sequence):
                done += 1
                self.progress_update.emit(self.node_id, done, total + 1)
        if self.is_cancelled:
            return
        image_nodes.publish(self.cache_dir, target, frames.working_scale, cancelled=lambda: self.is_cancelled)
        self.progress_update.emit(self.node_id, total + 1, total + 1)
        self.log_message.emit(self.node_id, "OCIO conversion complete.")
