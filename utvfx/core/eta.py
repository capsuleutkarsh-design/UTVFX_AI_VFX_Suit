"""Time left for a render, from its progress so far."""
import time


def format_duration(seconds):
    seconds = max(0, int(round(seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class Eta:
    """Estimates time left per node. Progress going backwards means a new render, so it starts over.

    The estimate waits for a little progress (early steps such as loading a model say little
    about the rest) and is smoothed so it does not jump with every frame.
    """

    MIN_FRACTION = 0.03
    MIN_SECONDS = 2.0
    SMOOTHING = 0.3  # weight of the newest estimate

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.runs = {}  # node id -> [start time, last fraction, smoothed seconds left]

    def reset(self, node_id):
        self.runs.pop(node_id, None)

    def update(self, node_id, fraction):
        """Record progress (0-1); returns seconds left, or None while it is too early to tell."""
        now = self.clock()
        run = self.runs.get(node_id)
        if run is None or fraction < run[1]:
            run = self.runs[node_id] = [now, fraction, None]
            return None
        run[1] = fraction
        elapsed = now - run[0]
        if fraction >= 1.0:
            return 0.0
        if fraction < self.MIN_FRACTION or elapsed < self.MIN_SECONDS:
            return None
        estimate = elapsed / fraction * (1.0 - fraction)
        run[2] = estimate if run[2] is None else (1 - self.SMOOTHING) * run[2] + self.SMOOTHING * estimate
        return run[2]

    def text(self, node_id, percentage):
        left = self.update(node_id, percentage / 100.0)
        if left is None or percentage >= 100:
            return f"{percentage}%"
        return f"{percentage}%  ·  {format_duration(left)} left"
