"""Low-latency PCM streaming into Discord.

:class:`PcmConverter` turns VOICEVOX ``s16le`` PCM (24 kHz mono by default) into the
48 kHz / 16-bit / stereo PCM Discord expects. It keeps interpolation state between
chunks, so splitting the input at arbitrary byte offsets produces exactly the same
output as converting it in one go (no clicks at segment boundaries).

:class:`StreamingPCMSource` is a :class:`discord.AudioSource` fed by a producer
thread while Discord's player thread reads 20 ms frames from it. It implements a
prebuffer, underrun detection (silence instead of blocking the player thread),
bounded memory with backpressure on the producer, and immediate disposal on stop.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from array import array
from collections import deque
from collections.abc import Callable

import discord

LOGGER = logging.getLogger(__name__)

DISCORD_SAMPLE_RATE = 48_000
DISCORD_CHANNELS = 2
SAMPLE_WIDTH = 2
FRAME_DURATION_SECONDS = 0.02
FRAME_SAMPLES = int(DISCORD_SAMPLE_RATE * FRAME_DURATION_SECONDS)
FRAME_SIZE = FRAME_SAMPLES * DISCORD_CHANNELS * SAMPLE_WIDTH
BYTES_PER_SECOND = DISCORD_SAMPLE_RATE * DISCORD_CHANNELS * SAMPLE_WIDTH
SILENCE_FRAME = bytes(FRAME_SIZE)
_BACKPRESSURE_POLL_SECONDS = 0.5
_BIG_ENDIAN = sys.byteorder == "big"


class PcmConverter:
    """Stateful linear-interpolation resampler from s16le PCM to Discord PCM.

    Output sample ``k`` is taken at input position ``k * in_rate / 48000``, computed
    with exact integer arithmetic so long streams never drift. The last input
    sample is held back until the next chunk (or :meth:`flush`) arrives because
    interpolation needs its successor.
    """

    def __init__(self, sample_rate: int, channels: int) -> None:
        if sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {sample_rate}")
        if channels not in {1, 2}:
            raise ValueError(f"channels must be 1 or 2, got {channels}")
        self._in_rate = sample_rate
        self._channels = channels
        self._input_frame_size = channels * SAMPLE_WIDTH
        self._pending = b""
        self._buffers: list[array[int]] = [array("h") for _ in range(channels)]
        # Absolute index (per channel) of ``self._buffers[c][0]``.
        self._base = 0
        self._total_in = 0
        self._out_index = 0

    def feed(self, data: bytes) -> bytes:
        """Convert a chunk; returns whatever output can be produced so far."""
        data = self._pending + data
        usable = len(data) - len(data) % self._input_frame_size
        self._pending = data[usable:]
        if usable:
            samples = array("h")
            samples.frombytes(data[:usable])
            if _BIG_ENDIAN:
                samples.byteswap()
            for channel, buffer in enumerate(self._buffers):
                buffer.extend(samples[channel :: self._channels])
            self._total_in += usable // self._input_frame_size
        return self._render(final=False)

    def flush(self) -> bytes:
        """Emit the remaining output at end of stream. A dangling odd byte is dropped."""
        self._pending = b""
        return self._render(final=True)

    def _render(self, *, final: bool) -> bytes:
        out_rate = DISCORD_SAMPLE_RATE
        in_rate = self._in_rate
        # Output k is producible when its right neighbour (i + 1) has arrived, or
        # when i itself exists at end of stream (the last sample is held).
        available = self._total_in if final else self._total_in - 1
        if available <= 0:
            return b""
        end = -(-available * out_rate // in_rate)  # ceil(available * out / in)
        start = self._out_index
        if end <= start:
            return b""

        positions = [divmod(k * in_rate, out_rate) for k in range(start, end)]
        channels_out = [
            _interpolate(buffer, positions, self._base, self._total_in - 1)
            for buffer in self._buffers
        ]
        self._out_index = end

        next_index = end * in_rate // out_rate
        drop = min(next_index, self._total_in) - self._base
        if drop > 0:
            for buffer in self._buffers:
                del buffer[:drop]
            self._base += drop

        left = channels_out[0]
        right = channels_out[1] if self._channels == DISCORD_CHANNELS else left
        stereo = array("h", bytes(len(left) * DISCORD_CHANNELS * SAMPLE_WIDTH))
        stereo[0::2] = array("h", left)
        stereo[1::2] = array("h", right)
        if _BIG_ENDIAN:
            stereo.byteswap()
        return stereo.tobytes()


def _interpolate(
    buffer: array[int],
    positions: list[tuple[int, int]],
    base: int,
    last: int,
) -> list[int]:
    """Linear interpolation at absolute input positions ``i + r / 48000``.

    Floor division keeps every result between its two neighbours, so int16 never
    overflows. The final sample (``last``) is held instead of reading past the end.
    """
    out_rate = DISCORD_SAMPLE_RATE
    return [
        (s0 := buffer[i - base]) + (buffer[min(i + 1, last) - base] - s0) * r // out_rate
        for i, r in positions
    ]


class StreamingPCMSource(discord.AudioSource):
    """Thread-safe 48 kHz stereo PCM buffer that Discord reads 20 ms frames from.

    Producer side (synthesis thread): :meth:`write`, then :meth:`finish`.
    Consumer side (Discord player thread): :meth:`read`.
    Either side, or the event loop: :meth:`close` discards everything.
    """

    def __init__(
        self,
        *,
        prebuffer_seconds: float,
        max_buffer_seconds: float,
        on_ready: Callable[[], None] | None = None,
    ) -> None:
        self._prebuffer_bytes = max(FRAME_SIZE, int(prebuffer_seconds * BYTES_PER_SECOND))
        self._max_buffer_bytes = max(
            self._prebuffer_bytes + FRAME_SIZE,
            int(max_buffer_seconds * BYTES_PER_SECOND),
        )
        self._on_ready = on_ready
        self._cond = threading.Condition()
        self._frames: deque[bytes] = deque()
        self._partial = bytearray()
        self._finished = False
        self._closed = False
        self._ready_notified = False
        self._rebuffering = False
        self.error: BaseException | None = None
        self.bytes_written = 0
        self.underruns = 0
        self.frames_played = 0
        self.first_read_at: float | None = None

    @property
    def buffered_bytes(self) -> int:
        with self._cond:
            return self._buffered_locked()

    @property
    def closed(self) -> bool:
        return self._closed

    def write(self, pcm: bytes) -> bool:
        """Append Discord-format PCM, blocking while the buffer is full.

        Returns ``False`` once the source has been closed, telling the producer to
        stop synthesizing.
        """
        notify = False
        with self._cond:
            while (
                not self._closed
                and self._buffered_locked() > 0
                and self._buffered_locked() + len(pcm) > self._max_buffer_bytes
            ):
                self._cond.wait(_BACKPRESSURE_POLL_SECONDS)
            if self._closed:
                return False
            if self._finished:
                raise RuntimeError("write() after finish()")
            self._partial += pcm
            while len(self._partial) >= FRAME_SIZE:
                self._frames.append(bytes(self._partial[:FRAME_SIZE]))
                del self._partial[:FRAME_SIZE]
            self.bytes_written += len(pcm)
            self._cond.notify_all()
            notify = self._take_ready_locked()
        if notify:
            self._notify_ready()
        return True

    def finish(self, error: BaseException | None = None) -> None:
        """Mark the end of input. Buffered audio still plays out (zero-padded)."""
        with self._cond:
            if not self._finished:
                self._finished = True
                self.error = error
                if self._partial:
                    self._partial.extend(bytes(FRAME_SIZE - len(self._partial)))
                    self._frames.append(bytes(self._partial))
                    self._partial.clear()
                self._cond.notify_all()
            notify = self._take_ready_locked()
        if notify:
            self._notify_ready()

    def close(self) -> None:
        """Discard all buffered audio and wake any waiting producer. Idempotent."""
        with self._cond:
            self._closed = True
            self._frames.clear()
            self._partial.clear()
            self._cond.notify_all()
            notify = self._take_ready_locked()
        if notify:
            self._notify_ready()

    def read(self) -> bytes:
        with self._cond:
            if self._closed:
                return b""
            if self.first_read_at is None:
                self.first_read_at = time.perf_counter()
            if self._rebuffering and (
                self._finished or self._buffered_locked() >= self._prebuffer_bytes
            ):
                self._rebuffering = False
            if not self._rebuffering and self._frames:
                frame = self._frames.popleft()
                self.frames_played += 1
                self._cond.notify_all()
                return frame
            if self._finished:
                return b""
            if not self._rebuffering:
                # Underrun: synthesis is slower than playback. Feed silence rather than
                # blocking the player thread, and refill before resuming.
                self._rebuffering = True
                self.underruns += 1
                LOGGER.debug("Streaming playback buffer underrun (%s)", self.underruns)
            return SILENCE_FRAME

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        self.close()

    def _buffered_locked(self) -> int:
        return len(self._frames) * FRAME_SIZE + len(self._partial)

    def _take_ready_locked(self) -> bool:
        if self._ready_notified:
            return False
        if self._closed or self._finished or self._buffered_locked() >= self._prebuffer_bytes:
            self._ready_notified = True
            return True
        return False

    def _notify_ready(self) -> None:
        if self._on_ready is not None:
            self._on_ready()


class ObservedSource(discord.AudioSource):
    """Delegating source that records when Discord first reads from it."""

    def __init__(self, inner: discord.AudioSource) -> None:
        self.inner = inner
        self.first_read_at: float | None = None

    def read(self) -> bytes:
        if self.first_read_at is None:
            self.first_read_at = time.perf_counter()
        return self.inner.read()

    def is_opus(self) -> bool:
        return self.inner.is_opus()

    def cleanup(self) -> None:
        self.inner.cleanup()
