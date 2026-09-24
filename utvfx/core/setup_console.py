"""How the first setup looks in the console: colours, a banner, numbered steps, progress
bars, a menu and a closing summary.

Standard library only, like first_setup.py: it runs on whatever Python starts the setup.
Colours are used only on a real console (and never with NO_COLOR set); redirected to a
file, the output is plain text with the same [OK] / [ERROR] tags as before.
"""
import builtins
import os
import re
import shutil
import sys
import time

APP = "Contour VFX"


def _enable_colour():
    if os.environ.get("NO_COLOR") or not getattr(sys.stdout, "isatty", lambda: False)():
        return False
    if os.name == "nt":  # turn on ANSI escape codes in the Windows console
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            return False
    return True


try:  # a console that cannot show a character gets "?" instead of a crash
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass
COLOUR = _enable_colour()
FANCY = COLOUR  # box and bar characters only on a real console

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = (f"\033[{n}m" for n in (91, 92, 93, 94, 95, 96, 97))
ACCENT = MAGENTA  # the node colour of Matte to Shape: Contour VFX's violet

TAG_COLOURS = {"OK": GREEN, "SUCCESS": GREEN, "FIX": GREEN, "ERROR": RED, "BAD": RED, "MISSING": YELLOW,
               "WARNING": YELLOW, "UNVERIFIED": YELLOW, "MANUAL": YELLOW, "SKIP": DIM, "DOWNLOAD": CYAN,
               "INFO": BLUE, "RUN": ACCENT}
_TAG = re.compile(r"^(\s*)\[([A-Z]+)\]")


def paint(text, *styles):
    return "".join(styles) + text + RESET if COLOUR and styles else text


def width():
    return max(60, min(shutil.get_terminal_size((80, 24)).columns - 2, 90))


def echo(*args, sep=" ", end="\n", file=None, flush=False):
    """print(), with a leading [TAG] coloured."""
    text = sep.join(str(a) for a in args)
    if COLOUR and file in (None, sys.stdout):
        text = "\n".join(_TAG.sub(lambda m: m.group(1) + paint(f"[{m.group(2)}]", BOLD, TAG_COLOURS.get(m.group(2), WHITE)), line)
                         for line in text.split("\n"))
    builtins.print(text, end=end, file=file, flush=flush)


def banner(version, subtitle="First setup"):
    w = width()
    if FANCY:
        line = "═" * (w - 2)
        builtins.print()
        builtins.print(paint("╔" + line + "╗", ACCENT))
        for text, style in ((f"{APP}  {version}", (BOLD, WHITE)), (subtitle, (CYAN,))):
            pad = w - 2 - len(text)
            builtins.print(paint("║", ACCENT) + " " * (pad // 2) + paint(text, *style) + " " * (pad - pad // 2) + paint("║", ACCENT))
        builtins.print(paint("╚" + line + "╝", ACCENT))
    else:
        builtins.print("=" * w)
        builtins.print(f" {APP} {version} - {subtitle}")
        builtins.print("=" * w)


def info_line(label, value, style=()):
    builtins.print(f"  {paint(label.ljust(12), DIM)}{paint(value, *style)}")


class Steps:
    """Numbered step headers: ── Step 2 of 4 · Python packages ──────"""

    def __init__(self):
        self.total, self.current = 0, 0

    def start(self, title):
        self.current += 1
        label = f"Step {self.current} of {self.total}" if self.total else f"Step {self.current}"
        head = f" {label} · {title} " if FANCY else f" {label}: {title} "
        rule = "─" if FANCY else "-"
        builtins.print()
        builtins.print(paint(rule * 2 + head + rule * max(3, width() - len(head) - 2), BOLD, ACCENT))

    def section(self, title):
        rule = "─" if FANCY else "-"
        builtins.print()
        builtins.print(paint(rule * 2 + f" {title} " + rule * max(3, width() - len(title) - 4), BOLD, ACCENT))


def format_size(n):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024.0:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} PB"


def format_time(seconds):
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"
    if seconds >= 60:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds}s"


def progress_bar(label):
    """A progress(done, total) callback: bar, percent, size, speed and time left, redrawn in place."""
    state = {"start": time.time(), "last": 0.0, "first": None}
    bar_w = 28

    def show(done, total):
        now = time.time()
        if state["first"] is None:
            state["first"] = done  # a resumed download: speed counts only this session's bytes
        if now - state["last"] < 0.2 and done < total:
            return
        state["last"] = now
        elapsed = max(now - state["start"], 1e-6)
        speed = (done - state["first"]) / elapsed
        if total > 0:
            frac = min(1.0, done / total)
            fill = int(bar_w * frac)
            bar = ("█" * fill + "░" * (bar_w - fill)) if FANCY else ("#" * fill + "-" * (bar_w - fill))
            left = format_time((total - done) / speed) if speed > 0 and done < total else "--"
            text = (f"  {paint(bar, CYAN)} {frac * 100:5.1f}%  {format_size(done)} / {format_size(total)}"
                    f"  {format_size(speed)}/s  {paint('left ' + left, DIM)}")
        else:
            text = f"  {format_size(done)}  {format_size(speed)}/s"
        sys.stdout.write("\r" + text + " " * 4)
        sys.stdout.flush()
    return show


def menu(title, options):
    """options: [(key, name, description)]. Returns the chosen key."""
    builtins.print()
    builtins.print(paint(f"  {title}", BOLD, WHITE))
    builtins.print()
    for key, name, description in options:
        builtins.print(f"   {paint(f'[{key}]', BOLD, ACCENT)}  {paint(name.ljust(22), BOLD)} {paint(description, DIM)}")
    keys = [o[0] for o in options]
    while True:
        builtins.print()
        try:
            choice = input(paint("  Choose an option and press Enter: ", CYAN)).strip()
        except EOFError:
            return keys[-1]
        if choice in keys:
            return choice
        echo(f"  [WARNING] Type one of: {', '.join(keys)}")


def ask(prompt):
    try:
        return input(paint(f"  {prompt}", CYAN)).strip().strip('"')
    except EOFError:
        return ""


def summary(ok, lines, elapsed):
    """The closing box: green when everything went well, red when something needs attention."""
    import textwrap
    colour = GREEN if ok else RED
    title = "All done" if ok else "Needs attention"
    w = width()
    wrapped = []  # long lines wrap inside the box, continuations indented under the text
    for line in lines + [f"Time taken: {format_time(elapsed)}"]:
        indent = " " * (len(_TAG.match(line).group(0)) + 1 if _TAG.match(line) else len(line) - len(line.lstrip()))
        wrapped += textwrap.wrap(line, w - 4, subsequent_indent=indent, drop_whitespace=True) or [""]
    lines = wrapped
    builtins.print()
    if FANCY:
        builtins.print(paint("┌─ " + title + " " + "─" * (w - len(title) - 5) + "┐", colour, BOLD))
        for line in lines:
            plain = _TAG.sub(lambda m: m.group(1) + f"[{m.group(2)}]", line)
            builtins.print(paint("│", colour, BOLD) + " " + _painted(line) + " " * max(0, w - 3 - len(plain)) + paint("│", colour, BOLD))
        builtins.print(paint("└" + "─" * (w - 2) + "┘", colour, BOLD))
    else:
        builtins.print("-" * w)
        builtins.print(f" {title}")
        for line in lines:
            builtins.print(" " + line)
        builtins.print("-" * w)


def _painted(line):
    if not COLOUR:
        return line
    return _TAG.sub(lambda m: m.group(1) + paint(f"[{m.group(2)}]", BOLD, TAG_COLOURS.get(m.group(2), WHITE)), line)
