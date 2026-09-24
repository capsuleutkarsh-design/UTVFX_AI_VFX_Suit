"""FIRST_SETUP's console: plain text when redirected, aligned boxes and a live progress line on a
console, and a menu whose choices map to the setup's options."""
import re

import first_setup
from utvfx.core import setup_console as ui

ANSI = re.compile(r"\033\[[0-9;]*m")


def test_redirected_output_is_plain(capsys, monkeypatch):
    monkeypatch.setattr(ui, "COLOUR", False)
    ui.echo("[OK] ready")
    assert capsys.readouterr().out == "[OK] ready\n"


def test_summary_box_lines_are_all_the_same_width(capsys, monkeypatch):
    monkeypatch.setattr(ui, "COLOUR", True)
    monkeypatch.setattr(ui, "FANCY", True)
    ui.summary(False, ["[ERROR] " + "a very long explanation " * 8, "[OK] short"], 75)
    lines = [ANSI.sub("", l) for l in capsys.readouterr().out.splitlines() if l]
    assert len({len(l) for l in lines}) == 1 and len(lines) > 4
    assert any("Time taken: 1m 15s" in l for l in lines)


def test_progress_line_shows_percent_size_and_time_left(capsys, monkeypatch):
    monkeypatch.setattr(ui, "COLOUR", False)
    monkeypatch.setattr(ui, "FANCY", False)
    clock = iter([100.0, 100.0, 110.0])  # start, first update, second update 10 s later
    monkeypatch.setattr(ui.time, "time", lambda: next(clock))
    show = ui.progress_bar("model.pth")
    show(0, 4 * 1024 ** 3)
    show(1024 ** 3, 4 * 1024 ** 3)
    out = capsys.readouterr().out
    assert "25.0%" in out and "1.0 GB / 4.0 GB" in out and "left 30s" in out  # 3 GB at 102.4 MB/s


def test_menu_choices_map_to_setup_options():
    keys = [k for k, _, _ in first_setup.MENU]
    assert keys == ["1", "2", "3", "4", "5", "0"]
    assert first_setup.MENU_ARGS == {"1": [], "2": ["--skip-models"], "4": ["--check"], "5": ["--verify"]}
