"""AI bridge client: slow replies, cancel and closed connections (no model is loaded)."""
import json
import socket
import threading
import time

import pytest

from utvfx.bridge.ai_bridge_client import AIBridgeClient, BridgeCancelled


def connected_client(server_behaviour):
    """A client wired to a fake engine through a socket pair."""
    a, b = socket.socketpair()
    client = AIBridgeClient()
    client.sock, client._rbuf, client.sock_in = a, b"", True
    client.sock_out = a.makefile("w", encoding="utf-8")
    client._stderr_tail = []
    threading.Thread(target=server_behaviour, args=(b,), daemon=True).start()
    return client


def test_a_reply_slower_than_the_poll_interval_still_arrives():
    """Regression: reading with a timeout once broke the stream ('cannot read from timed out object')."""
    def engine(conn):
        f = conn.makefile("r", encoding="utf-8")
        for _ in range(2):
            f.readline()
            time.sleep(2.5)  # longer than the client's 1 s poll
            conn.sendall(b'{"status": "ok", "objects": [1]}\n')

    client = connected_client(engine)
    assert client._request({"action": "x"}, timeout=10)["status"] == "ok"
    assert client._request({"action": "y"}, timeout=10)["objects"] == [1]  # the connection still works


def test_progress_lines_are_passed_on_and_split_packets_are_joined():
    def engine(conn):
        conn.makefile("r", encoding="utf-8").readline()
        conn.sendall(b'{"status": "progress", "done": 1}\n{"status": "o')
        time.sleep(0.2)
        conn.sendall(b'k"}\n')

    seen = []
    client = connected_client(engine)
    assert client._request({}, timeout=5, on_progress=seen.append)["status"] == "ok"
    assert seen == [{"status": "progress", "done": 1}]


def test_cancel_interrupts_a_long_request():
    def engine(conn):
        conn.makefile("r", encoding="utf-8").readline()
        time.sleep(30)

    client = connected_client(engine)
    client.process = None
    threading.Timer(0.5, client.cancel).start()
    started = time.time()
    with pytest.raises(BridgeCancelled):
        client._request({}, timeout=None)
    assert time.time() - started < 3


def test_engine_closing_is_reported():
    def engine(conn):
        conn.makefile("r", encoding="utf-8").readline()
        conn.close()

    client = connected_client(engine)
    client.process = None
    assert client._request({}, timeout=5) is None
    assert "closed the connection" in client.last_error
