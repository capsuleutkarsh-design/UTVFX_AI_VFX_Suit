"""Render a saved Contour VFX project without the window.

    python -m utvfx.cli shot.contour                      render every Unified Output node
    python -m utvfx.cli shot.contour --node Depth1        render one node (and what it needs)
    python -m utvfx.cli shot.contour --frames 1001-1050   limit to plate frames (like In/Out)
    python -m utvfx.cli shot.contour --relink D:/plates   look for missing plates in a folder
    python -m utvfx.cli shot.contour --list               show the nodes and stop

Exit codes: 0 all rendered, 1 a render failed or was cancelled, 2 bad arguments or project.
Frames are read and written exactly as the app does; nothing is uploaded anywhere.
"""
import argparse
import os
import signal
import sys
import time

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def parse_frames(text):
    """'1001-1050', '1001-', '-1050' or '1001' -> (first, last) plate frame numbers, None for an open end."""
    first, dash, last = str(text).strip().partition("-")
    try:
        first = int(first) if first else None
        last = (int(last) if last else None) if dash else first
    except ValueError:
        raise ValueError(f"Frames must look like 1001-1050, not '{text}'.")
    if first is None and last is None:
        raise ValueError(f"Frames must look like 1001-1050, not '{text}'.")
    return first, last


def plate_numbers(scene):
    """Plate frame numbers of the first Media Plate in the graph, as the timeline shows them."""
    from utvfx.core.plate import find_sequence
    for node in scene.nodes:
        if node.plugin_type != "media_plate":
            continue
        path = node.params.get("plate_file")
        if not path or not os.path.exists(path):
            continue
        if node.params.get("is_sequence", True) and os.path.isfile(path):
            return [n for n, _ in find_sequence(path)]
        from utvfx.playback.video_player import probe_media
        total = probe_media(path)[0]
        first = int(node.params.get("first_frame", 1) or 1)
        return list(range(first, first + total))
    return []


def frames_to_positions(numbers, first, last):
    """Plate frame numbers -> timeline positions (the engine's In/Out)."""
    inside = [i for i, n in enumerate(numbers) if (first is None or n >= first) and (last is None or n <= last)]
    if not inside:
        raise ValueError(f"No plate frames between {first} and {last} (the plate has {numbers[0]}-{numbers[-1]}).")
    return inside[0], inside[-1]


def choose_targets(scene, names):
    if names:
        found = []
        for name in names:
            node = next((n for n in scene.nodes if name in (n.name, n.node_id)), None)
            if node is None:
                raise ValueError(f"No node called '{name}'. Use --list to see the nodes.")
            found.append(node)
        return found
    outputs = [n for n in scene.nodes if n.plugin_type == "composite_output"]
    if not outputs:
        raise ValueError("The project has no Unified Output node; name the nodes to render with --node.")
    return outputs


def main(argv=None):
    parser = argparse.ArgumentParser(prog="contour-render", description="Render a Contour VFX project without the window.")
    parser.add_argument("project", help="the .contour project file")
    parser.add_argument("--node", action="append", help="node to render (name or id); repeatable")
    parser.add_argument("--frames", help="plate frames to render, e.g. 1001-1050 (like the timeline's In/Out)")
    parser.add_argument("--relink", help="folder to look in for plates that have moved")
    parser.add_argument("--list", action="store_true", help="list the project's nodes and stop")
    parser.add_argument("--quiet", action="store_true", help="only print progress and errors")
    args = parser.parse_args(argv)

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])

    from utvfx.core import project
    from utvfx.core.eta import Eta, format_duration
    from utvfx.core.settings_manager import SettingsManager
    from utvfx.ui.graph.scene import NodeScene

    try:
        data = project.load(args.project)
    except project.ProjectError as e:
        print(f"Cannot open {args.project}: {e}", file=sys.stderr)
        return EXIT_USAGE
    if args.relink:
        print(f"Relinked {project.relink(data, args.relink)} plate(s).")
    missing = project.missing_media(data)
    if missing:
        print("Missing plates (use --relink FOLDER):\n  " + "\n  ".join(p for _, p in missing), file=sys.stderr)
        return EXIT_USAGE

    SettingsManager().set_project_name(os.path.splitext(os.path.basename(args.project))[0], carry_cache=False)
    scene = NodeScene()
    scene.from_dict(data)
    if args.list:
        for node in scene.nodes:
            print(f"{node.name:28s} {node.plugin_type:20s} {node.node_id}")
        return EXIT_OK

    try:
        targets = choose_targets(scene, args.node)
        render_range = None
        if args.frames:
            numbers = plate_numbers(scene)
            if not numbers:
                raise ValueError("--frames needs a Media Plate with a readable plate.")
            render_range = frames_to_positions(numbers, *parse_frames(args.frames))
            print(f"Frames {numbers[render_range[0]]}-{numbers[render_range[1]]}.")
    except ValueError as e:
        print(e, file=sys.stderr)
        return EXIT_USAGE

    from utvfx.core.execution_engine import ExecutionEngine
    engine = ExecutionEngine(scene)
    engine.render_range = render_range
    names = {n.node_id: n.name for n in scene.nodes}
    eta, shown = Eta(), {}

    def on_log(node_id, message):
        if not args.quiet or "ERROR" in message:
            print(f"[{names.get(node_id, node_id)}] {message}", flush=True)

    def on_progress(node_id, pct):
        text = eta.text(node_id, pct)
        if pct != shown.get(node_id) and (pct % 5 == 0 or pct == 100):
            shown[node_id] = pct
            print(f"[{names.get(node_id, node_id)}] {text}", flush=True)

    engine.log_message.connect(on_log)
    engine.node_execution_progress.connect(on_progress)

    stop = {"asked": False}

    def interrupt(*_):
        if not stop["asked"]:
            stop["asked"] = True
            print("Stopping (Ctrl+C again to quit at once)...", file=sys.stderr, flush=True)
            engine.cancel_execution()
        else:
            os._exit(EXIT_FAILED)

    signal.signal(signal.SIGINT, interrupt)
    ticker = QTimer()  # lets Python see Ctrl+C while Qt's loop runs
    ticker.start(200)
    ticker.timeout.connect(lambda: None)

    code = EXIT_OK
    for node in targets:
        if stop["asked"]:
            code = EXIT_FAILED
            break
        loop, result = QEventLoop(), {}

        def finished(target, status, node_id=node.node_id):
            if target == node_id:
                result["status"] = status
                loop.quit()

        engine.pipeline_finished.connect(finished)
        start = time.monotonic()
        print(f"Rendering {node.name}...", flush=True)
        if engine.execute_node(node.node_id) is not False:
            loop.exec()
        engine.pipeline_finished.disconnect(finished)
        status = result.get("status", "rejected")
        print(f"{node.name}: {status} in {format_duration(time.monotonic() - start)}.", flush=True)
        if status != "done":
            code = EXIT_FAILED
    from utvfx.bridge.ai_bridge_client import AIBridgeClient
    if AIBridgeClient._instance is not None:
        AIBridgeClient._instance.shutdown()  # the SAM engine runs in its own process
    return code


if __name__ == "__main__":
    sys.exit(main())
