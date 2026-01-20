"""Append-only log for MintTouchedEvents (permanent storage)."""

import asyncio
import logging
import time
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, List, Optional

import aiofiles
import msgpack

from models.events import MintTouchedEvent

logger = logging.getLogger(__name__)

# File rotation settings (daily files for permanent storage)
ROTATION_INTERVAL_SECONDS = 86400  # New file every day


class EventLog:
    """
    Append-only log for MintTouchedEvents.

    - Stored permanently (no automatic cleanup)
    - Uses zstd-compressed msgpack for efficient storage
    - Rotates files daily
    - Useful for historical analysis and auditing
    """

    def __init__(self, data_dir: str = "data/event_logs"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._current_file: Optional[Any] = None  # aiofiles file handle
        self._current_file_time: int = 0
        self._write_lock = asyncio.Lock()
        self._buffer: List[bytes] = []
        self._buffer_size = 0
        self._max_buffer_size = 1024 * 1024  # 1MB buffer before flush

    async def start(self):
        """Start the event log."""
        logger.info(f"EventLog started, data_dir={self.data_dir}")

    async def stop(self):
        """Stop the event log and flush remaining buffer."""
        await self._flush_buffer()
        await self._close_current_file()
        logger.info("EventLog stopped")

    def _get_file_path(self, timestamp: int) -> Path:
        """Get file path for a given timestamp."""
        dt = datetime.utcfromtimestamp(timestamp)
        filename = dt.strftime("%Y%m%d.msgpack.zlib")
        return self.data_dir / filename

    async def _close_current_file(self):
        """Close current file if open."""
        if self._current_file:
            await self._current_file.close()
            self._current_file = None

    async def _get_file(self) -> Any:
        """Get current file handle, rotating if needed."""
        now = int(time.time())
        current_bucket = now // ROTATION_INTERVAL_SECONDS

        if self._current_file_time != current_bucket:
            await self._flush_buffer()
            await self._close_current_file()
            file_path = self._get_file_path(now)
            self._current_file = await aiofiles.open(file_path, "ab")
            self._current_file_time = current_bucket
            logger.debug(f"Rotated to new event log file: {file_path}")

        return self._current_file

    async def append(self, event: MintTouchedEvent):
        """Append a MintTouchedEvent to the log (buffered)."""
        data = event.to_msgpack()
        compressed = zlib.compress(data, level=1)

        # Length-prefix the record
        record = len(compressed).to_bytes(4, "big") + compressed

        async with self._write_lock:
            self._buffer.append(record)
            self._buffer_size += len(record)

            if self._buffer_size >= self._max_buffer_size:
                await self._flush_buffer()

    async def append_batch(self, events: List[MintTouchedEvent]):
        """Append multiple events efficiently."""
        if not events:
            return

        records = []
        total_size = 0

        for event in events:
            data = event.to_msgpack()
            compressed = zlib.compress(data, level=1)
            record = len(compressed).to_bytes(4, "big") + compressed
            records.append(record)
            total_size += len(record)

        async with self._write_lock:
            self._buffer.extend(records)
            self._buffer_size += total_size

            if self._buffer_size >= self._max_buffer_size:
                await self._flush_buffer()

    async def _flush_buffer(self):
        """Flush buffered records to disk."""
        if not self._buffer:
            return

        file = await self._get_file()

        for record in self._buffer:
            await file.write(record)
        await file.flush()

        logger.debug(f"Flushed {len(self._buffer)} events ({self._buffer_size} bytes)")
        self._buffer = []
        self._buffer_size = 0

    async def flush(self):
        """Force flush buffer to disk."""
        async with self._write_lock:
            await self._flush_buffer()

    async def read_day(
        self,
        date: datetime,
        mint_filter: Optional[str] = None
    ) -> AsyncIterator[MintTouchedEvent]:
        """Read all events from a specific day."""
        timestamp = int(date.timestamp())
        file_path = self._get_file_path(timestamp)

        if not file_path.exists():
            return

        async for event in self._read_file(file_path):
            if mint_filter is None or mint_filter in event.mints_touched:
                yield event

    async def _read_file(self, file_path: Path) -> AsyncIterator[MintTouchedEvent]:
        """Read all events from a single file."""
        try:
            async with aiofiles.open(file_path, "rb") as f:
                while True:
                    # Read length prefix
                    length_bytes = await f.read(4)
                    if not length_bytes or len(length_bytes) < 4:
                        break

                    length = int.from_bytes(length_bytes, "big")
                    if length <= 0 or length > 10_000_000:
                        logger.warning(f"Invalid record length {length} in {file_path}")
                        break

                    # Read compressed data
                    compressed = await f.read(length)
                    if len(compressed) < length:
                        break

                    # Decompress and deserialize
                    try:
                        data = zlib.decompress(compressed)
                        event = MintTouchedEvent.from_msgpack(data)
                        yield event
                    except Exception as e:
                        logger.warning(f"Failed to parse event in {file_path}: {e}")
                        continue
        except Exception as e:
            logger.error(f"Failed to read event log file {file_path}: {e}")

    async def get_stats(self) -> dict:
        """Get log statistics."""
        files = list(self.data_dir.glob("*.msgpack.zlib"))
        total_size = sum(f.stat().st_size for f in files)
        return {
            "file_count": len(files),
            "total_size_bytes": total_size,
            "total_size_mb": total_size / (1024 * 1024),
            "data_dir": str(self.data_dir),
            "buffer_pending": len(self._buffer),
            "buffer_size_bytes": self._buffer_size,
        }

    async def count_mints_touched_today(self) -> int:
        """Count unique mints touched today (for metrics)."""
        mints = set()
        async for event in self.read_day(datetime.utcnow()):
            mints.update(event.mints_touched)
        return len(mints)
