from __future__ import annotations

import math
import threading
from array import array
from itertools import pairwise

import pytest

from yomiage.audio_stream import (
    BYTES_PER_SECOND,
    FRAME_SIZE,
    SILENCE_FRAME,
    PcmConverter,
    StreamingPCMSource,
)


def _pcm(samples: list[int]) -> bytes:
    return array("h", samples).tobytes()


def _samples(data: bytes) -> list[int]:
    values = array("h")
    values.frombytes(data)
    return values.tolist()


def _sine(count: int, rate: int = 24_000) -> list[int]:
    return [int(12_000 * math.sin(2 * math.pi * 440 * n / rate)) for n in range(count)]


def _convert_in_chunks(data: bytes, chunk_sizes: list[int], rate: int, channels: int) -> bytes:
    converter = PcmConverter(rate, channels)
    output = bytearray()
    offset = 0
    for size in chunk_sizes:
        output += converter.feed(data[offset : offset + size])
        offset += size
    output += converter.feed(data[offset:])
    output += converter.flush()
    return bytes(output)


# --- PcmConverter -----------------------------------------------------------------


def test_converter_upsamples_mono_24k_to_48k_stereo() -> None:
    converter = PcmConverter(24_000, 1)
    output = converter.feed(_pcm([0, 100, 200])) + converter.flush()
    samples = _samples(output)
    left, right = samples[0::2], samples[1::2]
    assert left == right
    # Interpolated midpoints between input samples; the last sample is held.
    assert left == [0, 50, 100, 150, 200, 200]


def test_converter_output_length_matches_duration() -> None:
    converter = PcmConverter(24_000, 1)
    output = converter.feed(_pcm(_sine(24_000))) + converter.flush()
    assert len(output) == BYTES_PER_SECOND


def test_converter_passes_48k_through() -> None:
    converter = PcmConverter(48_000, 1)
    output = converter.feed(_pcm([1, -2, 3])) + converter.flush()
    assert _samples(output) == [1, 1, -2, -2, 3, 3]


def test_converter_keeps_stereo_channels_separate() -> None:
    converter = PcmConverter(24_000, 2)
    output = converter.feed(_pcm([0, 1000, 100, 1100])) + converter.flush()
    samples = _samples(output)
    assert samples[0::2] == [0, 50, 100, 100]
    assert samples[1::2] == [1000, 1050, 1100, 1100]


@pytest.mark.parametrize("rate", [24_000, 44_100, 22_050, 16_000])
@pytest.mark.parametrize(
    "chunk_sizes",
    [
        [2],
        [7201, 7199],  # odd byte split mid-sample
        [1, 1, 1, 3, 5, 997],
        [14_400, 14_400],  # VOICEVOX-like 0.3 s segments
    ],
)
def test_chunk_boundaries_do_not_change_output(rate: int, chunk_sizes: list[int]) -> None:
    data = _pcm(_sine(rate // 2, rate))
    one_shot = _convert_in_chunks(data, [], rate, 1)
    chunked = _convert_in_chunks(data, chunk_sizes, rate, 1)
    assert chunked == one_shot
    assert len(one_shot) % 4 == 0


def test_converter_output_is_continuous_across_segments() -> None:
    """No jumps larger than the source signal allows (i.e. no clicks at boundaries)."""
    source = _sine(24_000)
    data = _pcm(source)
    output = _samples(_convert_in_chunks(data, [14_400] * 3, 24_000, 1))[0::2]
    max_source_step = max(abs(b - a) for a, b in pairwise(source))
    max_output_step = max(abs(b - a) for a, b in pairwise(output))
    assert max_output_step <= max_source_step


def test_converter_extreme_values_do_not_overflow() -> None:
    converter = PcmConverter(22_050, 1)
    output = converter.feed(_pcm([32_767, -32_768] * 100)) + converter.flush()
    assert all(-32_768 <= value <= 32_767 for value in _samples(output))


def test_converter_rejects_invalid_format() -> None:
    with pytest.raises(ValueError, match="channels"):
        PcmConverter(24_000, 3)
    with pytest.raises(ValueError, match="sample_rate"):
        PcmConverter(0, 1)


# --- StreamingPCMSource -----------------------------------------------------------


def _source(
    prebuffer: float = 0.1,
    max_buffer: float = 1.0,
    on_ready: threading.Event | None = None,
) -> StreamingPCMSource:
    return StreamingPCMSource(
        prebuffer_seconds=prebuffer,
        max_buffer_seconds=max_buffer,
        on_ready=on_ready.set if on_ready is not None else None,
    )


def test_source_returns_exact_20ms_frames_and_pads_tail() -> None:
    source = _source()
    payload = bytes(range(256)) * 40  # 10240 bytes = 2 frames + 2560 bytes
    assert source.write(payload)
    source.finish()

    frames = []
    while frame := source.read():
        frames.append(frame)
    assert [len(frame) for frame in frames] == [FRAME_SIZE] * 3
    assert b"".join(frames)[: len(payload)] == payload
    assert frames[-1][len(payload) - 2 * FRAME_SIZE :] == bytes(3 * FRAME_SIZE - len(payload))
    assert source.read() == b""


def test_source_frames_are_contiguous_across_writes() -> None:
    source = _source()
    payload = bytes(index % 251 for index in range(FRAME_SIZE * 3))
    for offset in range(0, len(payload), 1000):
        source.write(payload[offset : offset + 1000])
    source.finish()
    assert b"".join(iter(source.read, b"")) == payload


def test_source_ready_after_prebuffer_or_finish() -> None:
    ready = threading.Event()
    source = _source(prebuffer=0.1, on_ready=ready)
    source.write(bytes(FRAME_SIZE))
    assert not ready.is_set()
    source.write(bytes(int(0.1 * BYTES_PER_SECOND)))
    assert ready.is_set()

    short_ready = threading.Event()
    short = _source(prebuffer=1.0, on_ready=short_ready)
    short.write(bytes(FRAME_SIZE))
    assert not short_ready.is_set()
    short.finish()  # short text: do not wait for a full prebuffer
    assert short_ready.is_set()


def test_source_underrun_plays_silence_and_rebuffers() -> None:
    source = _source(prebuffer=0.06)  # 3 frames
    source.write(b"\x01" * FRAME_SIZE)
    assert source.read() == b"\x01" * FRAME_SIZE
    assert source.read() == SILENCE_FRAME
    assert source.underruns == 1
    # Still rebuffering after one frame arrives: refill to the prebuffer first.
    source.write(b"\x02" * FRAME_SIZE)
    assert source.read() == SILENCE_FRAME
    assert source.underruns == 1
    source.write(b"\x02" * FRAME_SIZE * 2)
    assert source.read() == b"\x02" * FRAME_SIZE
    # End of stream during rebuffering drains what is left instead of waiting.
    source.read()
    source.read()
    assert source.read() == SILENCE_FRAME
    assert source.underruns == 2
    source.write(b"\x03" * FRAME_SIZE)
    source.finish()
    assert source.read() == b"\x03" * FRAME_SIZE
    assert source.read() == b""


def test_source_backpressure_blocks_producer_until_read() -> None:
    source = _source(prebuffer=0.02, max_buffer=0.1)  # 5 frames
    source.write(bytes(FRAME_SIZE * 5))
    released = threading.Event()

    def produce() -> None:
        source.write(bytes(FRAME_SIZE))
        released.set()

    thread = threading.Thread(target=produce)
    thread.start()
    assert not released.wait(0.2)
    assert source.buffered_bytes == FRAME_SIZE * 5
    source.read()
    assert released.wait(2.0)
    thread.join(2.0)
    assert source.buffered_bytes == FRAME_SIZE * 5


def test_source_close_discards_buffer_and_unblocks_producer() -> None:
    source = _source(prebuffer=0.02, max_buffer=0.1)
    source.write(bytes(FRAME_SIZE * 5))
    result: list[bool] = []
    thread = threading.Thread(target=lambda: result.append(source.write(bytes(FRAME_SIZE))))
    thread.start()
    source.close()
    thread.join(2.0)
    assert not thread.is_alive()
    assert result == [False]
    assert source.buffered_bytes == 0
    assert source.read() == b""
    assert source.write(b"x") is False
    source.cleanup()  # idempotent


def test_source_finish_records_error() -> None:
    source = _source()
    error = RuntimeError("boom")
    source.finish(error)
    assert source.error is error
    assert source.read() == b""
