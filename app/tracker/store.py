import asyncio
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_EMPTY_STORE = {"version": 1, "companies": []}


class JSONStore:
    """
    Atomic read/write for a single JSON file.
    Uses os.replace() for atomic writes on Windows and POSIX.
    """

    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()

    async def load(self) -> dict:
        if not self.path.exists():
            return dict(_EMPTY_STORE)
        return await asyncio.to_thread(self._sync_load)

    async def save(self, data: dict) -> None:
        async with self._lock:
            await asyncio.to_thread(self._sync_save, data)

    def _sync_load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load %s: %s — returning empty store", self.path, e)
            return dict(_EMPTY_STORE)

    def _sync_save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Backup existing file before overwriting
        if self.path.exists():
            backup = self.path.with_suffix(".backup.json")
            shutil.copy2(self.path, backup)

        # Write to a temp file in the same directory, then atomically replace
        fd, tmp_path = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp_path, self.path)  # atomic on both Windows and POSIX
            logger.debug("Saved %s", self.path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
