"""Time-left estimate for the progress bar."""
from utvfx.core.eta import Eta, format_duration


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_estimate_after_some_progress_and_restart():
    clock = Clock()
    eta = Eta(clock)
    assert eta.text("n", 0) == "0%"
    clock.t = 1.0
    assert eta.text("n", 1) == "1%"            # too early to tell
    clock.t = 10.0
    assert eta.text("n", 10) == "10%  ·  1:30 left"  # 10 s for 10% -> 90 s left
    clock.t = 20.0
    eta.text("n", 20)
    clock.t = 25.0
    assert eta.text("n", 5) == "5%"            # progress went back: a new render
    assert eta.text("n", 100) == "100%"


def test_format():
    assert format_duration(59.6) == "1:00" and format_duration(3725) == "1:02:05"
