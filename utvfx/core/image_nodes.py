"""Shared reading and writing for nodes that change pictures (Grade, OCIO ColorSpace).

They read the full-quality pixels of their input (a plate's master, or EXR/PNG output of
another node), not the 16-bit display copy, and publish their result as a plate of
their own: tagged EXRs that keep alpha (the master) plus the display copy the AI
nodes and the viewer use. The node's output port points at that display copy, as for
a Media Plate, so any node downstream finds the master through plate_for_folder().
"""
import os
import shutil

import numpy as np

from utvfx.core import colour, exr
from utvfx.core.plate import Plate, find_sequence, plate_for_folder

FRAMES = "Frames"  # the node's master EXRs, inside its cache folder


class Frames:
    """The frames arriving at an image input: numbers, colour space and a reader."""

    def __init__(self, folder, cancelled=None):
        if not folder or not os.path.isdir(folder):
            raise Exception("Nothing is wired into Image (or the node before it has not rendered).")
        self.plate = plate_for_folder(folder)
        if self.plate is not None:
            self.plate.ensure("master", cancelled=cancelled)
            self.sequence = list(zip(self.plate.frame_numbers, self.plate.paths("master")))
            # A sequence plate's master is the original files; a video's is decoded to ACEScg.
            self.decoded = self.plate.m["kind"] == "video"
            self.colourspace = colour.SCENE_LINEAR if self.decoded else self.plate.colourspace
            self.working_scale = float(self.plate.m.get("working_scale", 1.0))
        else:
            self.decoded = False
            self.sequence = find_sequence(folder)
            self.colourspace = colour.detect_colourspace(self.sequence[0][1]) if self.sequence else colour.AUTO
            self.working_scale = 1.0
        if not self.sequence:
            raise Exception(f"No frames found in {folder}.")

    def read(self, path, space=None):
        """(rgb, alpha or None) as float32; rgb converted from `space` (default: the input's) to ACEScg."""
        pixels = colour.read_image(path)[0]
        rgb, alpha = colour._split(pixels)
        return colour.to_scene_linear(rgb, space or self.colourspace), alpha


def start_output(cache_dir):
    """An empty folder for the master frames; the old display copy goes too (In/Out may shrink it)."""
    from utvfx.core.plate import MANIFEST, TIER_FOLDERS
    for name in (FRAMES, *TIER_FOLDERS.values()):
        shutil.rmtree(os.path.join(cache_dir, name), ignore_errors=True)
    if os.path.isfile(os.path.join(cache_dir, MANIFEST)):
        os.remove(os.path.join(cache_dir, MANIFEST))
    folder = os.path.join(cache_dir, FRAMES)
    os.makedirs(folder)
    return folder


def write_frame(folder, number, rgb, alpha, space):
    """One master frame: half-float EXR, alpha kept, tagged so every reader knows its colour space."""
    pixels = rgb if alpha is None else np.concatenate([rgb, alpha], axis=2)
    channels = ("R", "G", "B") if alpha is None else ("R", "G", "B", "A")
    chroma = colour.AP1_CHROMATICITIES if space == colour.SCENE_LINEAR else None
    exr.write(os.path.join(folder, f"frame_{number:06d}.exr"), pixels, channels,
              chromaticities=chroma, attributes={"oiio:ColorSpace": space})


def publish(cache_dir, space, working_scale=1.0, cancelled=None):
    """Turn the node's master frames into a plate and build the display copy."""
    plate = Plate.prepare(os.path.join(cache_dir, FRAMES), cache_dir, colourspace=space,
                          working_scale=working_scale)
    plate.ensure("png16", cancelled=cancelled)
    return plate
