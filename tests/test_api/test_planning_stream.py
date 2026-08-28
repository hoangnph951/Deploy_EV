from queue import Queue

from src.apps.api.routes.trips import _planning_event_stream


def test_planning_stream_emits_heartbeat_while_worker_is_silent() -> None:
    events: Queue[dict] = Queue()
    stream = _planning_event_stream(events, heartbeat_seconds=0.001)

    first = next(stream)

    assert '"type": "heartbeat"' in first


def test_planning_stream_stops_after_done_event() -> None:
    events: Queue[dict] = Queue()
    events.put({"type": "done"})

    assert list(_planning_event_stream(events, heartbeat_seconds=0.001)) == [
        'data: {"type": "done"}\n\n'
    ]
