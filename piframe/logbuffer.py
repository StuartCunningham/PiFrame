"""In-memory ring buffer that captures Python log records for the web UI."""
import collections
import logging
import threading
import time

_MAX_ENTRIES = 500


class LogBuffer:
    def __init__(self):
        self._lock = threading.Lock()
        self._entries = collections.deque(maxlen=_MAX_ENTRIES)
        self._seq = 0

    def append(self, level: str, name: str, message: str):
        with self._lock:
            self._seq += 1
            self._entries.append({
                'seq': self._seq,
                't': time.strftime('%H:%M:%S'),
                'level': level,
                'name': name,
                'msg': message,
            })

    def since(self, seq: int) -> list:
        with self._lock:
            return [e for e in self._entries if e['seq'] > seq]

    def latest_seq(self) -> int:
        with self._lock:
            return self._seq


class _LogHandler(logging.Handler):
    def __init__(self, buf: LogBuffer):
        super().__init__()
        self._buf = buf

    def emit(self, record: logging.LogRecord):
        try:
            self._buf.append(record.levelname, record.name, record.getMessage())
        except Exception:
            self.handleError(record)


_buffer = LogBuffer()


def get_buffer() -> LogBuffer:
    return _buffer


def install():
    """Attach the handler to the root logger (call once at startup)."""
    logging.getLogger().addHandler(_LogHandler(_buffer))
