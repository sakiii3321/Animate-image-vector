"""Atomic JSON publication and worker progress forwarding."""
from contextlib import contextmanager
import json
from pathlib import Path
import threading
import time


def write_json_atomic(path, data, *, optional=False):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    text = json.dumps(data, ensure_ascii=False)
    for attempt in range(6):
        try:
            temporary.write_text(text, encoding='utf-8')
            temporary.replace(path)
            return True
        except PermissionError:
            # A polling reader (or another Windows process) may briefly hold
            # the destination without FILE_SHARE_DELETE, blocking replacement.
            if attempt < 5:
                time.sleep(.01 * 2 ** attempt)
                continue
            if not optional:
                raise
        except OSError:
            if not optional:
                raise
        # Progress is advisory. Keep the previous complete JSON and let the
        # next update retry; losing one update must not abort image processing.
        return False


@contextmanager
def forward_progress(path, record):
    """Forward changed worker status until the surrounding process finishes."""
    if record is None:
        yield
        return
    path = Path(path)
    stopped = threading.Event()

    def observe():
        last = None
        while not stopped.wait(.4):
            try:
                state = json.loads(path.read_text(encoding='utf-8'))
                if state != last:
                    last = state.copy()
                    stage = state.pop('stage')
                    record(stage, **state)
            except (OSError, ValueError, KeyError):
                continue

    observer = threading.Thread(target=observe, daemon=True)
    observer.start()
    try:
        yield
    finally:
        stopped.set()
        observer.join(timeout=2)
