"""Execution engine: Stop, refusal, errors, Freeze, render range and the render queue (H4, H5, H7)."""
import os
import time

import pytest

from utvfx.bridge.base_worker import BaseWorker
from utvfx.core.commands import ConnectCommand
from utvfx.core.execution_engine import ExecutionEngine


class FakeWorker(BaseWorker):
    """Writes one frame, optionally slowly, optionally failing."""
    delay = 0.0
    fail = False
    seen_ranges = []

    def run_task(self):
        FakeWorker.seen_ranges.append(self.frame_range)
        end = time.time() + self.delay
        while time.time() < end:
            if self.is_cancelled:
                return
            time.sleep(0.01)
        if self.fail:
            raise RuntimeError("boom")
        os.makedirs(self.cache_dir, exist_ok=True)
        open(os.path.join(self.cache_dir, "frame_0001.png"), "wb").write(b"x")


@pytest.fixture
def engine(node_scene, tmp_path, monkeypatch):
    from utvfx.core import plugin_manager

    monkeypatch.setattr(ExecutionEngine, "cache_dir", property(lambda self: str(tmp_path / "cache")))
    monkeypatch.setattr(ExecutionEngine, "temp_dir", property(lambda self: str(tmp_path / "temp")))
    monkeypatch.setattr(plugin_manager.PluginManager, "get_worker_class", lambda self, plugin: FakeWorker)
    FakeWorker.delay, FakeWorker.fail, FakeWorker.seen_ranges = 0.0, False, []
    eng = ExecutionEngine(node_scene)
    yield eng
    for w in list(eng.active_workers.values()):
        w.cancel()
        w.wait(2000)


def chain(node_scene):
    from utvfx.core.data_model import NODES_REGISTRY
    reg = NODES_REGISTRY["grade"]
    a = node_scene.add_node("A", "grade", reg["inputs"], reg["outputs"])
    b = node_scene.add_node("B", "grade", reg["inputs"], reg["outputs"])
    a.params, b.params = {}, {}
    ConnectCommand(node_scene, a.outputs[0], b.inputs[0]).redo()
    return a, b


def test_stop_with_another_node_selected_stops_the_running_render(engine, node_scene, qtbot):
    a, b = chain(node_scene)
    FakeWorker.delay = 30
    with qtbot.waitSignal(engine.node_execution_started):
        engine.execute_node(b.node_id)
    assert a.node_id in engine.active_workers  # upstream node is the one running
    with qtbot.waitSignal(engine.pipeline_finished, timeout=5000) as blocker:
        engine.cancel_execution(b.node_id)  # Stop pressed with the downstream node selected
    assert blocker.args == [b.node_id, "cancelled"]
    assert not engine.active_workers and not engine.is_executing_pipeline


def test_second_render_is_refused_while_one_runs(engine, node_scene, qtbot):
    a, b = chain(node_scene)
    FakeWorker.delay = 30
    engine.execute_node(a.node_id)
    with qtbot.waitSignal(engine.pipeline_finished) as blocker:
        assert engine.execute_node(b.node_id) is False
    assert blocker.args == [b.node_id, "rejected"]
    with qtbot.waitSignal(engine.pipeline_finished, timeout=5000):
        engine.cancel_execution()


def test_error_ends_the_pipeline(engine, node_scene, qtbot):
    a, b = chain(node_scene)
    FakeWorker.fail = True
    with qtbot.waitSignal(engine.pipeline_finished, timeout=5000) as blocker:
        engine.execute_node(b.node_id)
    assert blocker.args == [b.node_id, "error"]
    assert not engine.is_executing_pipeline


def test_pipeline_runs_to_done_and_caches(engine, node_scene, qtbot):
    a, b = chain(node_scene)
    with qtbot.waitSignal(engine.pipeline_finished, timeout=5000) as blocker:
        engine.execute_node(b.node_id)
    assert blocker.args == [b.node_id, "done"]
    FakeWorker.seen_ranges = []
    with qtbot.waitSignal(engine.pipeline_finished, timeout=5000):
        engine.execute_node(b.node_id)
    assert FakeWorker.seen_ranges == []  # both nodes were served from the cache


def test_frozen_node_is_not_re_rendered(engine, node_scene, qtbot):
    a, b = chain(node_scene)
    with qtbot.waitSignal(engine.pipeline_finished, timeout=5000):
        engine.execute_node(a.node_id)
    a.is_frozen = True
    a.params["gain"] = 2.0  # would normally invalidate the cache
    a.set_execution_state(True, 0)  # used to clear the freeze flag
    assert a.is_frozen
    FakeWorker.seen_ranges = []
    with qtbot.waitSignal(engine.pipeline_finished, timeout=5000):
        engine.execute_node(a.node_id)
    assert FakeWorker.seen_ranges == []


def test_render_range_reaches_the_worker_and_the_cache_key(engine, node_scene, qtbot):
    a, _ = chain(node_scene)
    before = engine._compute_node_hash(a)
    engine.render_range = (4, 9)
    assert engine._compute_node_hash(a) != before
    with qtbot.waitSignal(engine.pipeline_finished, timeout=5000):
        engine.execute_node(a.node_id)
    assert FakeWorker.seen_ranges == [(4, 9)]


def test_worker_positions_honour_the_range():
    w = FakeWorker("n", {}, {}, ".", ".")
    assert list(w.positions(5)) == [0, 1, 2, 3, 4]
    w.frame_range = (1, 3)
    assert list(w.positions(5)) == [1, 2, 3]
    w.frame_range = (None, 10)
    assert list(w.positions(5)) == [0, 1, 2, 3, 4]


def test_render_queue_moves_past_a_failed_node(engine, node_scene, qtbot):
    from types import SimpleNamespace
    from utvfx.ui.windows.render_queue import RenderQueueDialog

    a, b = chain(node_scene)
    queue = RenderQueueDialog(SimpleNamespace(execution_engine=engine))
    qtbot.addWidget(queue)
    queue.add_node(a)
    queue.add_node(b)
    FakeWorker.fail = True
    queue.start_queue()
    qtbot.waitUntil(lambda: not queue.is_rendering, timeout=5000)
    assert queue.queue_items == []
    assert len(queue.failed) == 2
