"""Body-parts mode of Matte to Shape: a person's matte cut into head, torso and limb shapes.

MediaPipe Pose finds the skeleton on every frame; each matte pixel goes to the nearest bone,
so the parts always add up to the whole matte (no gaps). Matte to Shape then turns each
part into a shape with its own steady tracking. With a depth map, a limb well behind the
torso fades out and comes back when it is in front again.
"""
import os

import cv2
import numpy as np

# name: (joint a, joint b). Joint numbers are MediaPipe Pose's; "neck" is between the shoulders.
BONES = {
    "Head": ("neck", 0),
    "L_Upper_Arm": (11, 13), "L_Forearm": (13, 15),
    "R_Upper_Arm": (12, 14), "R_Forearm": (14, 16),
    "L_Thigh": (23, 25), "L_Calf": (25, 27),
    "R_Thigh": (24, 26), "R_Calf": (26, 28),
}
TORSO = (11, 12, 24, 23)  # shoulders and hips, as a quad
PARTS = ["Torso"] + list(BONES)
MIN_VISIBILITY = 0.3      # MediaPipe still guesses joints it cannot see; those guesses are not used


def _segment_distance(pts, a, b):
    v = b - a
    length = float(v @ v)
    if length == 0:
        return np.linalg.norm(pts - a, axis=1)
    t = np.clip(((pts - a) @ v) / length, 0.0, 1.0)
    return np.linalg.norm(pts - (a + t[:, None] * v), axis=1)


def detect_skeletons(frames, read_bgr, cancelled=lambda: False):
    """{frame: {joint: (x, y, visibility)}} for the frames MediaPipe finds a person in."""
    from mediapipe.python.solutions import pose as mp_pose
    found = {}
    detector = mp_pose.Pose(static_image_mode=False, min_detection_confidence=0.5, model_complexity=1)
    try:
        for number, path in frames:
            if cancelled():
                break
            img = read_bgr(path)
            if img is None:
                continue
            h, w = img.shape[:2]
            result = detector.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            if result.pose_landmarks:
                found[number] = {i: (lm.x * w, lm.y * h, lm.visibility)
                                 for i, lm in enumerate(result.pose_landmarks.landmark)}
    finally:
        detector.close()
    return found


def fill_and_smooth(found, numbers):
    """Skeletons for every frame: gaps filled from neighbours, positions smoothed over 3 frames
    (so the cuts between parts do not flicker). Joints never seen well stay missing."""
    joints = {}
    for j in range(33):
        seen = [(n, found[n][j]) for n in numbers if n in found and found[n][j][2] >= MIN_VISIBILITY]
        if not seen:
            continue
        xs = np.interp(numbers, [n for n, _ in seen], [p[0] for _, p in seen])
        ys = np.interp(numbers, [n for n, _ in seen], [p[1] for _, p in seen])
        if len(numbers) >= 3:
            xs = np.convolve(np.pad(xs, 1, mode="edge"), np.ones(3) / 3, mode="valid")
            ys = np.convolve(np.pad(ys, 1, mode="edge"), np.ones(3) / 3, mode="valid")
        joints[j] = (xs, ys)
    out = {}
    for k, n in enumerate(numbers):
        skel = {}
        for j, (xs, ys) in joints.items():
            skel[j] = np.array([xs[k], ys[k]], np.float32)  # dropouts are filled from neighbours
        if 11 in skel and 12 in skel:
            skel["neck"] = 0.5 * (skel[11] + skel[12])
        out[n] = skel
    return out


def split(matte, skeleton, min_area=100):
    """{part: contour} for one frame: every matte pixel goes to its nearest bone or the torso."""
    ys, xs = np.nonzero(matte)
    if len(xs) == 0:
        return {}
    pts = np.stack([xs, ys], axis=1).astype(np.float32)
    names, dists = [], []
    if all(j in skeleton for j in TORSO):
        quad = np.array([skeleton[j] for j in TORSO], np.float32)
        edge = np.min([_segment_distance(pts, quad[i], quad[(i + 1) % 4]) for i in range(4)], axis=0)
        hull = cv2.convexHull(quad).reshape(-1, 2)
        names.append("Torso")
        dists.append(np.where(_in_convex(pts, hull), 0.0, edge))  # inside the torso quad: torso
    for name, (a, b) in BONES.items():
        if a in skeleton and b in skeleton:
            names.append(name)
            dists.append(_segment_distance(pts, skeleton[a], skeleton[b]))
    if not names:
        return {}
    owner = np.argmin(np.stack(dists, axis=1), axis=1)
    parts = {}
    kernel = np.ones((5, 5), np.uint8)
    for k, name in enumerate(names):
        sel = owner == k
        if sel.sum() < min_area:
            continue
        mask = np.zeros(matte.shape, np.uint8)
        mask[ys[sel], xs[sel]] = 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            best = max(contours, key=cv2.contourArea)
            if cv2.contourArea(best) >= min_area:
                parts[name] = best
    return parts


def _in_convex(pts, poly):
    """Vectorised point-in-convex-polygon test (for large mattes)."""
    inside = np.ones(len(pts), bool)
    sign = None
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        cross = (b[0] - a[0]) * (pts[:, 1] - a[1]) - (b[1] - a[1]) * (pts[:, 0] - a[0])
        s = np.sign(cross)
        if sign is None:
            sign = np.sign(np.median(s)) or 1
        inside &= (s * sign) >= 0
    return inside


# ---- depth: limbs behind the body --------------------------------------------------
def depth_convention(path):
    """How a depth map is encoded: the Depth node records it; other maps are taken as near = 1."""
    if path.lower().endswith(".exr"):
        import OpenImageIO as oiio
        inp = oiio.ImageInput.open(path)
        if inp:
            spec = inp.spec()
            inp.close()
            return spec.get_string_attribute("contour/depth") or "relative, near = 1"
    return "relative, near = 1"


def read_depth(path, convention):
    """Depth as 'nearness' (larger = closer), or metres if the map is metric."""
    from utvfx.core import exr
    if path.lower().endswith(".exr"):
        depth = exr.read(path)[0][..., 0]
    else:
        depth = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if depth is None:
            return None
        if depth.ndim == 3:
            depth = depth[..., 0]
        depth = depth.astype(np.float32) / (65535.0 if depth.dtype == np.uint16 else 255.0)
    if convention == "relative, near = 0":
        depth = 1.0 - depth
    return depth.astype(np.float32)


def behind_amount(part_depth, torso_depth, convention):
    """How much farther than the torso a part is, as a fraction of the torso's distance (+ = behind)."""
    if convention == "metric":
        return (part_depth - torso_depth) / max(torso_depth, 1e-6)
    return (torso_depth - part_depth) / max(torso_depth, 1e-6)


def part_depths(parts, depth, matte):
    """Median depth inside each part (and inside the matte)."""
    out = {}
    for name, cnt in parts.items():
        mask = np.zeros(matte.shape, np.uint8)
        cv2.drawContours(mask, [cnt], -1, 1, -1)
        inside = (mask > 0) & matte
        if inside.any():
            out[name] = float(np.median(depth[inside]))
    return out


class Occlusion:
    """Hysteresis per part: fade out when well behind the torso, back in when in front again."""

    def __init__(self, hide_above, show_below, step=0.25):
        self.hide_above, self.show_below, self.step = hide_above, show_below, step
        self.opacity = {}

    def update(self, name, behind):
        current = self.opacity.get(name, 1.0)
        target = current
        if behind is not None:
            if behind > self.hide_above:
                target = 0.0
            elif behind < self.show_below:
                target = 1.0
        if target < current:
            current = max(0.0, current - self.step)
        elif target > current:
            current = min(1.0, current + self.step)
        self.opacity[name] = current
        return current


def depth_frames(folder):
    from utvfx.core.plate import find_sequence
    if not folder or not os.path.isdir(folder):
        return {}, None
    frames = dict(find_sequence(folder))
    return frames, (depth_convention(next(iter(frames.values()))) if frames else None)
