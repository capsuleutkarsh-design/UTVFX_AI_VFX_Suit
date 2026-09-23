"""Grade: Nuke's Grade in scene-linear ACEScg, on the full-quality frames, alpha untouched.

    A = multiply * (gain - lift) / (whitepoint - blackpoint)
    B = offset + lift - A * blackpoint
    out = (A * in + B) ** (1 / gamma)     (gamma only on positive values)
"""
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from utvfx.bridge.base_worker import BaseWorker
from utvfx.core import colour, image_nodes


def grade(rgb, blackpoint=0.0, whitepoint=1.0, lift=0.0, gain=1.0, multiply=1.0, offset=0.0, gamma=1.0,
          black_clamp=True, white_clamp=False):
    a = multiply * (gain - lift) / (whitepoint - blackpoint if abs(whitepoint - blackpoint) > 1e-6 else 1e-6)
    b = offset + lift - a * blackpoint
    out = a * rgb + b
    if gamma != 1.0:
        out = np.where(out > 0, np.power(np.maximum(out, 0), 1.0 / max(gamma, 1e-6)), out)
    if black_clamp:
        out = np.maximum(out, 0.0)
    if white_clamp:
        out = np.minimum(out, 1.0)
    return out.astype(np.float32)


class GradeWorker(BaseWorker):
    def run_task(self):
        p = self.params
        values = {k: float(p.get(k, d)) for k, d in (("blackpoint", 0.0), ("whitepoint", 1.0), ("lift", 0.0),
                                                     ("gain", 1.0), ("multiply", 1.0), ("offset", 0.0),
                                                     ("gamma", 1.0))}
        values["black_clamp"] = bool(p.get("black_clamp", True))
        values["white_clamp"] = bool(p.get("white_clamp", False))
        unpremult = bool(p.get("unpremult", False))

        frames = image_nodes.Frames(self.inputs.get("Image"), cancelled=lambda: self.is_cancelled)
        sequence = [frames.sequence[i] for i in self.positions(len(frames.sequence))]
        out = image_nodes.start_output(self.cache_dir)
        total = len(sequence)
        self.log_message.emit(self.node_id, f"Grading {total} frames in ACEScg ({frames.colourspace} input).")

        def work(item):
            number, path = item
            if self.is_cancelled:
                return
            rgb, alpha = frames.read(path)
            if unpremult and alpha is not None:
                safe = np.where(alpha > 1e-6, alpha, 1.0)
                rgb = grade(rgb / safe, **values) * np.where(alpha > 1e-6, alpha, 0.0)
            else:
                rgb = grade(rgb, **values)
            image_nodes.write_frame(out, number, rgb, alpha, colour.SCENE_LINEAR)

        done = 0
        with ThreadPoolExecutor(max(2, min(6, (os.cpu_count() or 4) - 2))) as pool:
            for _ in pool.map(work, sequence):
                done += 1
                self.progress_update.emit(self.node_id, done, total + 1)
        if self.is_cancelled:
            return
        image_nodes.publish(self.cache_dir, colour.SCENE_LINEAR, frames.working_scale,
                            cancelled=lambda: self.is_cancelled)
        self.progress_update.emit(self.node_id, total + 1, total + 1)
        self.log_message.emit(self.node_id, "Grade complete.")
