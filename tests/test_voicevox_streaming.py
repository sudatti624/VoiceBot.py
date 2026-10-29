"""VoicevoxSynthesizer streaming adapter, tested without the native VOICEVOX runtime."""

from __future__ import annotations

import wave
from collections import OrderedDict
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from threading import Lock

import pytest

from yomiage.config import Settings
from yomiage.voicevox import (
    PcmFormat,
    StreamingNotSupportedError,
    VoicevoxConfigError,
    VoicevoxPcmStream,
    VoicevoxSynthesizer,
    parse_wav_header,
    validate_synthesis_mode,
)

PCM = bytes(range(256)) * 30  # 7680 bytes
SEGMENTS = [PCM[:3000], PCM[3000:6000], PCM[6000:]]


def _wav(pcm: bytes, rate: int = 24_000, channels: int = 1) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


HEADER = _wav(PCM)[:44]


class FakeNativeStream:
    """Mimics voicevox_core.blocking.SynthesisStream after the header was consumed."""

    def __init__(self, segments: list[bytes], *, fail_at: int | None = None) -> None:
        self._segments = list(segments)
        self._fail_at = fail_at
        self._index = 0
        self.cleared = False

    def __iter__(self) -> FakeNativeStream:
        return self

    def __next__(self) -> bytes:
        if self._fail_at is not None and self._index == self._fail_at:
            raise RuntimeError("RunModelError")
        if self._index >= len(self._segments):
            raise StopIteration
        segment = self._segments[self._index]
        self._index += 1
        return segment

    def clear(self) -> None:
        self.cleared = True
        self._segments.clear()


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    settings = Settings(
        discord_token="test-token",  # noqa: S106 - test fixture, not a real secret
        bot_id=0,
        database_path=tmp_path / "test.sqlite3",
        max_tokens=400,
        speaker_id=3,
        speed=1.2,
        voicevox_onnxruntime_path=tmp_path / "onnxruntime",
        open_jtalk_dict_dir=tmp_path / "dict",
        voicevox_model_path=tmp_path / "model.vvm",
        voicevox_model_exclude=(),
        voicevox_acceleration_mode="CPU",
        cache_size=10,
        ffmpeg_path="ffmpeg",
    )
    return replace(settings, **overrides)  # pyright: ignore[reportArgumentType]


def _synthesizer(
    settings: Settings,
    streaming: frozenset[int] = frozenset({3}),
) -> VoicevoxSynthesizer:
    """Build the adapter without loading ONNX Runtime, OpenJTalk or VVMs."""
    synth = object.__new__(VoicevoxSynthesizer)
    synth.settings = settings
    synth._cache = OrderedDict()
    synth._lock = Lock()
    synth._style_model_paths = {3: Path("3.vvm"), 8: Path("8.vvm")}
    synth._streaming_style_ids = set(streaming)
    synth._streaming_style_id_set = streaming
    synth._loaded_model_paths = set()
    synth._style_ids = frozenset({3, 8})
    return synth


def _stream(
    synth: VoicevoxSynthesizer,
    native: FakeNativeStream,
    text: str = "テスト",
) -> VoicevoxPcmStream:
    return VoicevoxPcmStream(synth, native, HEADER, synth._cache_key(text, 3))  # pyright: ignore[reportArgumentType]


def test_parse_wav_header_reads_streaming_format() -> None:
    assert parse_wav_header(HEADER) == PcmFormat(sample_rate=24_000, channels=1)
    assert parse_wav_header(_wav(b"\0\0\0\0", 48_000, 2)[:44]) == PcmFormat(48_000, 2)


def test_completed_stream_is_cached_as_full_wav(tmp_path: Path) -> None:
    synth = _synthesizer(_settings(tmp_path))
    native = FakeNativeStream(SEGMENTS)
    with _stream(synth, native) as stream:
        assert b"".join(stream) == PCM
    assert synth.get_cached("テスト", 3) == _wav(PCM)


def test_cancelled_stream_is_not_cached(tmp_path: Path) -> None:
    synth = _synthesizer(_settings(tmp_path))
    native = FakeNativeStream(SEGMENTS)
    with _stream(synth, native) as stream:
        next(iter(stream))
    assert native.cleared
    assert synth.get_cached("テスト", 3) is None


def test_failed_stream_is_not_cached(tmp_path: Path) -> None:
    synth = _synthesizer(_settings(tmp_path))
    native = FakeNativeStream(SEGMENTS, fail_at=1)
    with pytest.raises(RuntimeError, match="RunModelError"), _stream(synth, native) as stream:
        list(stream)
    assert native.cleared
    assert synth.get_cached("テスト", 3) is None


def test_truncated_stream_is_not_cached(tmp_path: Path) -> None:
    synth = _synthesizer(_settings(tmp_path))
    with _stream(synth, FakeNativeStream(SEGMENTS[:2])) as stream:
        list(stream)
    assert synth.get_cached("テスト", 3) is None


def test_cache_disabled_keeps_nothing(tmp_path: Path) -> None:
    synth = _synthesizer(_settings(tmp_path, cache_size=0))
    with _stream(synth, FakeNativeStream(SEGMENTS)) as stream:
        assert b"".join(stream) == PCM
    assert synth.get_cached("テスト", 3) is None


def test_cache_key_includes_style_and_speed(tmp_path: Path) -> None:
    synth = _synthesizer(_settings(tmp_path))
    with synth.lock:
        synth.store_cache_locked(synth._cache_key("テスト", 3), b"wav")
    assert synth.get_cached("テスト", 3) == b"wav"
    assert synth.get_cached("テスト", 8) is None
    faster = _synthesizer(_settings(tmp_path, speed=1.5))
    faster._cache = synth._cache
    assert faster.get_cached("テスト", 3) is None


def test_cache_is_lru_bounded(tmp_path: Path) -> None:
    synth = _synthesizer(_settings(tmp_path, cache_size=2))
    with synth.lock:
        for text in ("a", "b"):
            synth.store_cache_locked(synth._cache_key(text, 3), text.encode())
    assert synth.get_cached("a", 3) == b"a"  # refresh "a"
    with synth.lock:
        synth.store_cache_locked(synth._cache_key("c", 3), b"c")
    assert synth.get_cached("b", 3) is None
    assert synth.get_cached("a", 3) == b"a"


def test_open_stream_rejects_old_format_style(tmp_path: Path) -> None:
    synth = _synthesizer(_settings(tmp_path))
    assert synth.supports_streaming(3)
    assert not synth.supports_streaming(8)
    with pytest.raises(StreamingNotSupportedError, match="streaming_talk"):
        synth.open_stream("テスト", 8)


def test_validate_synthesis_mode_normal_ignores_streaming_support(tmp_path: Path) -> None:
    synth = _synthesizer(_settings(tmp_path), streaming=frozenset())
    validate_synthesis_mode(_settings(tmp_path, synthesis_mode="normal"), synth)


def test_validate_synthesis_mode_streaming_requires_streaming_default_speaker(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, synthesis_mode="streaming", speaker_id=8)
    with pytest.raises(VoicevoxConfigError, match="VOICEVOX_SYNTHESIS_MODE=streaming"):
        validate_synthesis_mode(settings, _synthesizer(settings))
    validate_synthesis_mode(replace(settings, speaker_id=3), _synthesizer(settings))


def test_validate_synthesis_mode_auto_allows_old_vvms(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = _settings(tmp_path, synthesis_mode="auto")
    validate_synthesis_mode(settings, _synthesizer(settings, streaming=frozenset()))
    assert "normal synthesis" in caplog.text
