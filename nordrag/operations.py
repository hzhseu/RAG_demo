"""A single operation across builder and chat processes sharing the same data directory."""
import os
import threading
from pathlib import Path


class OperationLock:
    def __init__(self, home: Path, filename="operation.lock"):
        home.mkdir(parents=True, exist_ok=True)
        self.path = home / filename
        self.local = threading.Lock()
        self.file = None

    def acquire(self, blocking=False):
        if not self.local.acquire(blocking=blocking):
            return False
        try:
            self.file = self.path.open("a+b")
            if self.file.seek(0, 2) == 0:
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if self.file:
                self.file.close()
            self.file = None
            self.local.release()
            return False

    def locked(self):
        return self.local.locked()

    def release(self):
        if self.file:
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_UN)
            self.file.close()
            self.file = None
        self.local.release()
