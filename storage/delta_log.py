"""Append-only log for TxDeltaRecords with rotation."""

import asyncio
import logging
import os
import time
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, List, Optional

import aiofiles
import msgpack

from config.settings import settings
from models.events import TxDeltaRecord

logger = logging.getLogger(__name__)

# File rotation settings
ROTATION_INTERVAL_SECONDS = 300  # New file every 5 minutes
MAX_FILE_AGE_SECONDS = settings.delta_log_retention_minutes * 60


class DeltaLog:
    """
    Append-only log for TxDeltaRecords.

    - Uses zstd-compressed msgpack for efficient storage
    - Rotates files every 5 minutes
    - Automatically cleans up files older than retention period
    - Allows re-reading records when token becomes HOT
    """

    def __init__(self, data_dir: str = "data/delta_logs"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._current_file: Optional[Any] = None  # aiofiles file handle
        self._current_file_time: int = 0
        self._write_lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the delta log with cleanup task."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info(f"DeltaLog started, data_dir={self.data_dir}")

    async def stop(self):
        """Stop the delta log and close files."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        await self._close_current_file()
        logger.info("DeltaLog stopped")

    def _get_file_path(self, timestamp: int) -> Path:
        """Get file path for a given timestamp."""
        bucket = timestamp // ROTATION_INTERVAL_SECONDS
        dt = datetime.utcfromtimestamp(bucket * ROTATION_INTERVAL_SECONDS)
        filename = dt.strftime("%Y%m%d_%H%M%S.msgpack.zlib")
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
            await self._close_current_file()
            file_path = self._get_file_path(now)
            self._current_file = await aiofiles.open(file_path, "ab")
            self._current_file_time = current_bucket
            logger.debug(f"Rotated to new delta log file: {file_path}")

        return self._current_file

    async def append(self, record: TxDeltaRecord):
        """Append a TxDeltaRecord to the log."""
        async with self._write_lock:
            file = await self._get_file()

            # Serialize with msgpack and compress
            data = record.to_msgpack()
            compressed = zlib.compress(data, level=1)  # Fast compression

            # Write length-prefixed record
            length = len(compressed)
            await file.write(length.to_bytes(4, "big"))
            await file.write(compressed)
            await file.flush()

    async def append_batch(self, records: List[TxDeltaRecord]):
        """Append multiple records efficiently."""
        if not records:
            return

        async with self._write_lock:
            file = await self._get_file()

            for record in records:
                data = record.to_msgpack()
                compressed = zlib.compress(data, level=1)
                length = len(compressed)
                await file.write(length.to_bytes(4, "big"))
                await file.write(compressed)

            await file.flush()

    async def read_recent(
        self,
        max_age_seconds: Optional[int] = None,
        mint_filter: Optional[str] = None
    ) -> AsyncIterator[TxDeltaRecord]:
        """
        Read recent records from log files.

        Args:
            max_age_seconds: Only read files created within this time window
            mint_filter: Only yield records that touched this mint
        """
        if max_age_seconds is None:
            max_age_seconds = MAX_FILE_AGE_SECONDS

        cutoff_time = int(time.time()) - max_age_seconds

        # Get all log files sorted by time
        files = sorted(self.data_dir.glob("*.msgpack.zlib"))

        for file_path in files:
            # Parse timestamp from filename
            try:
                name_part = file_path.stem.replace(".msgpack", "")
                file_time = datetime.strptime(name_part, "%Y%m%d_%H%M%S")
                file_timestamp = int(file_time.timestamp())
            except ValueError:
                continue

            # Skip files outside time window
            if file_timestamp < cutoff_time:
                continue

            # Read records from file
            async for record in self._read_file(file_path):
                if mint_filter is None or mint_filter in record.mints_touched:
                    yield record

    async def _read_file(self, file_path: Path) -> AsyncIterator[TxDeltaRecord]:
        """Read all records from a single file."""
        try:
            async with aiofiles.open(file_path, "rb") as f:
                while True:
                    # Read length prefix
                    length_bytes = await f.read(4)
                    if not length_bytes or len(length_bytes) < 4:
                        break

                    length = int.from_bytes(length_bytes, "big")
                    if length <= 0 or length > 10_000_000:  # Sanity check
                        logger.warning(f"Invalid record length {length} in {file_path}")
                        break

                    # Read compressed data
                    compressed = await f.read(length)
                    if len(compressed) < length:
                        break

                    # Decompress and deserialize
                    try:
                        data = zlib.decompress(compressed)
                        record = TxDeltaRecord.from_msgpack(data)
                        yield record
                    except Exception as e:
                        logger.warning(f"Failed to parse record in {file_path}: {e}")
                        continue
        except Exception as e:
            logger.error(f"Failed to read delta log file {file_path}: {e}")

    async def read_for_mint(
        self,
        mint: str,
        max_age_seconds: Optional[int] = None
    ) -> List[TxDeltaRecord]:
        """Read all recent records for a specific mint."""
        records = []
        async for record in self.read_recent(max_age_seconds, mint_filter=mint):
            records.append(record)
        return records

    async def _cleanup_loop(self):
        """Periodically clean up old log files."""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                await self._cleanup_old_files()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")

    async def _cleanup_old_files(self):
        """Delete log files older than retention period."""
        cutoff_time = int(time.time()) - MAX_FILE_AGE_SECONDS
        deleted = 0
        current_bucket = self._current_file_time

        for file_path in self.data_dir.glob("*.msgpack.zlib"):
            try:
                name_part = file_path.stem.replace(".msgpack", "")
                file_time = datetime.strptime(name_part, "%Y%m%d_%H%M%S")
                file_timestamp = int(file_time.timestamp())
                file_bucket = file_timestamp // ROTATION_INTERVAL_SECONDS

                # Skip currently open file (avoid Windows lock errors)
                if current_bucket and file_bucket == current_bucket:
                    continue

                if file_timestamp < cutoff_time:
                    file_path.unlink()
                    deleted += 1
            except (ValueError, OSError) as e:
                logger.warning(f"Failed to process/delete {file_path}: {e}")

        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old delta log files")

    async def get_stats(self) -> dict:
        """Get log statistics."""
        files = list(self.data_dir.glob("*.msgpack.zlib"))
        total_size = sum(f.stat().st_size for f in files)
        return {
            "file_count": len(files),
            "total_size_bytes": total_size,
            "total_size_mb": total_size / (1024 * 1024),
            "data_dir": str(self.data_dir),
        }
