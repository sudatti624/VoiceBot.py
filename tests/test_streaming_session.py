"""SessionManager behaviour for normal / streaming / auto synthesis modes.

Runs without Discord or VOICEVOX: ``FakeVoiceClient`` emulates discord.py's player
thread (reads 20 ms frames until ``b""`` then calls ``after`` and ``cleanup``) and
``FakeStreamingSynthesizer`` yields PCM segments the way ``streaming_synthesis`` does.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from types import TracebackType
from typing import Self

import discord
import pytest

from yomiage.audio_stream import FRAME_SIZE
from yomiage.config import Settings, VoicevoxSynthesisMode
from yomiage.database import Database
from yomiage.speech import MAX_CONSECUTIVE_STREAMING_FAILURES, SessionManager, SpeechItem
from yomiage.translator import Translator
from yomiage.voicevox import PcmFormat

SEGMENT = bytes(range(1, 241)) * 60  # 14400 bytes = 0.3 s of 24 kHz mono s16le
SEGMENT_FRAMES = 15  # 0.3 s at 48 kHz stereo / 20 ms frames
TIMEOUT = 5.0


class FakeVoiceClient(discord.VoiceClient):
    """Player-thread emulation; bypasses the real VoiceClient constructor."""

    def __init__(self) -> None:  # pyright: ignore[reportMissingSuperCall]
        self.frames: list[bytes] = []
        self.sources: list[discord.AudioSource] = []
        self.play_started = threading.Event()
        self.frame_delay = 0.001
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def play(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        source: discord.AudioSource,
        *,
        after: Callable[[Exception | None], object] | None = None,
    ) -> None:
        self.sources.append(source)
        self._stop = threading.Event()
        stop = self._stop

        def run() -> None:
            try:
                while not stop.is_set():
                    data = source.read()
                    if not data:
                        break
                    self.frames.append(data)
                    self.play_started.set()
                    time.sleep(self.frame_delay)
            finally:
                if after is not None:
                    after(None)
                source.cleanup()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self) -> None:
        if self._thread is not None:
            self._thread.join(TIMEOUT)


class FakeGuild:
    def __init__(self, guild_id: int, voice_client: object | None) -> None:
        self.id = guild_id
        self.voice_client = voice_client


class FakeStream:
    def __init__(self, owner: FakeStreamingSynthesizer, segments: list[bytes]) -> None:
        self._owner = owner
        self._segments = iter(segments)
        self._index = 0
        self.closed = False

    @property
    def format(self) -> PcmFormat:
        return PcmFormat(sample_rate=24_000, channels=1)

    def __iter__(self) -> Iterator[bytes]:
        return self

    def __next__(self) -> bytes:
        owner = self._owner
        gate = owner.gates.get(self._index)
        if gate is not None:
            assert gate.wait(TIMEOUT), f"gate {self._index} never opened"
        if owner.fail_at is not None and self._index == owner.fail_at:
            raise RuntimeError("synthesis failed")
        segment = next(self._segments)
        self._index += 1
        owner.segments_produced += 1
        owner.segment_produced.set()
        return segment

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.closed = True


class FakeStreamingSynthesizer:
    def __init__(
        self,
        *,
        segments: int = 3,
        streaming_styles: frozenset[int] = frozenset({3}),
    ) -> None:
        self.segment_count = segments
        self.streaming_styles = streaming_styles
        self.cache: dict[tuple[str, int], bytes] = {}
        self.gates: dict[int, threading.Event] = {}
        self.fail_at: int | None = None
        self.fail_open = False
        self.generate_calls: list[str] = []
        self.stream_calls: list[str] = []
        self.streams: list[FakeStream] = []
        self.segments_produced = 0
        self.segment_produced = threading.Event()

    def generate(self, text: str, speaker_id: int | None = None) -> bytes:  # noqa: ARG002
        self.generate_calls.append(text)
        return b"RIFF-normal-" + text.encode()

    def is_style_available(self, style_id: int) -> bool:  # noqa: ARG002
        return True

    def available_style_ids(self) -> frozenset[int]:
        return frozenset({1, 3})

    def get_cached(self, text: str, speaker_id: int | None = None) -> bytes | None:
        return self.cache.get((text, speaker_id or 3))

    def supports_streaming(self, style_id: int) -> bool:
        return style_id in self.streaming_styles

    def streaming_style_ids(self) -> frozenset[int]:
        return self.streaming_styles

    def open_stream(self, text: str, speaker_id: int | None = None) -> FakeStream:  # noqa: ARG002
        self.stream_calls.append(text)
        if self.fail_open:
            raise RuntimeError("model does not support streaming")
        stream = FakeStream(self, [SEGMENT] * self.segment_count)
        self.streams.append(stream)
        return stream


class IdentityTranslator(Translator):
    """Keeps test text verbatim so assertions can compare it directly."""

    def convert(self, source_text: str, server_id: int, bot_id: int) -> str:  # noqa: ARG002
        return source_text


class RecordingPlayback:
    """Replaces ``_play_wav_data`` so normal playback never spawns ffmpeg."""

    def __init__(self) -> None:
        self.played: list[bytes] = []

    async def __call__(
        self,
        _voice_client: discord.VoiceClient,
        wav_data: bytes,
        _metrics: object = None,
    ) -> None:
        self.played.append(wav_data)


def _make_settings(tmp_path: Path, mode: VoicevoxSynthesisMode) -> Settings:
    return Settings(
        discord_token="test-token",  # noqa: S106 - test fixture, not a real secret
        bot_id=0,
        database_path=tmp_path / f"test-{mode}.sqlite3",
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
        synthesis_mode=mode,
        stream_segment_seconds=0.3,
        stream_buffer_seconds=0.5,
        performance_log=True,
    )


class Harness:
    def __init__(
        self,
        tmp_path: Path,
        mode: VoicevoxSynthesisMode,
        synth: FakeStreamingSynthesizer,
    ) -> None:
        self.settings = _make_settings(tmp_path, mode)
        self.database = Database(self.settings.database_path)
        self.synth = synth
        self.manager = SessionManager(
            self.settings,
            self.database,
            IdentityTranslator(self.database),
            self.synth,
        )
        self.playback = RecordingPlayback()
        self.manager._play_wav_data = self.playback  # pyright: ignore[reportAttributeAccessIssue]

    def close(self) -> None:
        self.database.close()


HarnessFactory = Callable[..., Harness]


@pytest.fixture
def make_harness(tmp_path: Path) -> Iterator[HarnessFactory]:
    harnesses: list[Harness] = []

    def factory(
        mode: VoicevoxSynthesisMode,
        *,
        segments: int = 3,
        streaming_styles: frozenset[int] = frozenset({3}),
    ) -> Harness:
        synth = FakeStreamingSynthesizer(segments=segments, streaming_styles=streaming_styles)
        harness = Harness(tmp_path, mode, synth)
        harnesses.append(harness)
        return harness

    yield factory
    for harness in harnesses:
        harness.close()


async def _speak(harness: Harness, voice_client: FakeVoiceClient, text: str) -> None:
    guild = FakeGuild(1, voice_client)
    await asyncio.wait_for(
        harness.manager._speak_one(guild, SpeechItem(text=text, speaker_id=3)),  # pyright: ignore[reportArgumentType]
        TIMEOUT,
    )
    voice_client.join()


def _streamed_audio(voice_client: FakeVoiceClient) -> bytes:
    return b"".join(frame for frame in voice_client.frames if any(frame))


# --- mode selection ---------------------------------------------------------------


def test_normal_mode_regression_uses_generate(make_harness: HarnessFactory) -> None:
    harness = make_harness("normal")
    voice_client = FakeVoiceClient()
    asyncio.run(_speak(harness, voice_client, "こんにちは"))
    assert harness.synth.generate_calls == ["こんにちは"]
    assert harness.synth.stream_calls == []
    assert harness.playback.played == ["RIFF-normal-こんにちは".encode()]
    assert voice_client.sources == []


def test_streaming_mode_streams_all_segments(make_harness: HarnessFactory) -> None:
    harness = make_harness("streaming", segments=4)
    voice_client = FakeVoiceClient()
    asyncio.run(_speak(harness, voice_client, "ストリーミング"))
    assert harness.synth.generate_calls == []
    assert harness.synth.stream_calls == ["ストリーミング"]
    assert len(voice_client.sources) == 1
    assert len(_streamed_audio(voice_client)) == 4 * SEGMENT_FRAMES * FRAME_SIZE
    assert all(len(frame) == FRAME_SIZE for frame in voice_client.frames)
    assert harness.synth.streams[0].closed


def test_auto_mode_streams_supported_style(make_harness: HarnessFactory) -> None:
    harness = make_harness("auto")
    voice_client = FakeVoiceClient()
    asyncio.run(_speak(harness, voice_client, "自動"))
    assert harness.synth.stream_calls == ["自動"]
    assert harness.synth.generate_calls == []


@pytest.mark.parametrize("mode", ["streaming", "auto"])
def test_unsupported_style_uses_normal_synthesis(
    make_harness: HarnessFactory,
    mode: VoicevoxSynthesisMode,
) -> None:
    """Old-format VVM styles cannot stream, so they are read with normal synthesis."""
    harness = make_harness(mode, streaming_styles=frozenset())
    voice_client = FakeVoiceClient()
    asyncio.run(_speak(harness, voice_client, "旧形式"))
    assert harness.synth.stream_calls == []
    assert harness.synth.generate_calls == ["旧形式"]


def test_playback_starts_before_synthesis_completes(make_harness: HarnessFactory) -> None:
    harness = make_harness("streaming", segments=5)
    last_segment = threading.Event()
    harness.synth.gates[4] = last_segment
    voice_client = FakeVoiceClient()

    async def scenario() -> None:
        task = asyncio.create_task(_speak(harness, voice_client, "長い文章"))
        assert await asyncio.to_thread(voice_client.play_started.wait, TIMEOUT)
        # Discord is already reading audio while the last segment is not synthesized.
        assert harness.synth.segments_produced == 4
        assert not task.done()
        last_segment.set()
        await task

    asyncio.run(scenario())
    assert len(_streamed_audio(voice_client)) == 5 * SEGMENT_FRAMES * FRAME_SIZE


def test_buffer_underrun_is_counted(
    make_harness: HarnessFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = make_harness("streaming", segments=3)
    gate = threading.Event()
    harness.synth.gates[2] = gate
    voice_client = FakeVoiceClient()

    async def scenario() -> None:
        task = asyncio.create_task(_speak(harness, voice_client, "遅い合成"))
        assert await asyncio.to_thread(voice_client.play_started.wait, TIMEOUT)
        await asyncio.sleep(0.2)  # player drains the buffer and starts emitting silence
        gate.set()
        await task

    caplog.set_level("INFO", logger="yomiage.perf")
    asyncio.run(scenario())
    assert any(not any(frame) for frame in voice_client.frames)
    assert len(_streamed_audio(voice_client)) == 3 * SEGMENT_FRAMES * FRAME_SIZE
    perf_lines = [r.getMessage() for r in caplog.records if "speech_perf" in r.getMessage()]
    assert len(perf_lines) == 1
    assert "path=streaming" in perf_lines[0]
    assert "underruns=1" in perf_lines[0]
    assert "first_audio_ms=n/a" not in perf_lines[0]
    assert "playback_start_ms=n/a" not in perf_lines[0]


# --- errors and fallback ----------------------------------------------------------


def test_auto_falls_back_when_streaming_fails_before_playback(
    make_harness: HarnessFactory,
) -> None:
    harness = make_harness("auto")
    harness.synth.fail_open = True
    voice_client = FakeVoiceClient()
    asyncio.run(_speak(harness, voice_client, "フォールバック"))
    assert harness.synth.stream_calls == ["フォールバック"]
    assert harness.synth.generate_calls == ["フォールバック"]
    assert voice_client.sources == []
    assert len(harness.playback.played) == 1


def test_auto_falls_back_on_error_during_prebuffer(make_harness: HarnessFactory) -> None:
    harness = make_harness("auto", segments=3)
    harness.synth.fail_at = 1  # one segment buffered, nothing played yet
    voice_client = FakeVoiceClient()
    asyncio.run(_speak(harness, voice_client, "途中失敗"))
    assert voice_client.sources == []
    assert harness.synth.generate_calls == ["途中失敗"]
    assert harness.synth.streams[0].closed


def test_no_fallback_after_playback_started(make_harness: HarnessFactory) -> None:
    """Falling back after audio reached Discord would read the message twice."""
    harness = make_harness("auto", segments=5)
    harness.synth.fail_at = 3  # fails only once Discord is already playing
    gate = threading.Event()
    harness.synth.gates[3] = gate
    voice_client = FakeVoiceClient()

    async def scenario() -> None:
        task = asyncio.create_task(_speak(harness, voice_client, "二重読み上げ防止"))
        assert await asyncio.to_thread(voice_client.play_started.wait, TIMEOUT)
        gate.set()
        await task

    asyncio.run(scenario())
    assert len(voice_client.sources) == 1
    assert harness.synth.generate_calls == []
    assert harness.playback.played == []
    # Audio produced before the error is played out, nothing more.
    assert len(_streamed_audio(voice_client)) == 3 * SEGMENT_FRAMES * FRAME_SIZE


def test_streaming_mode_does_not_fall_back(make_harness: HarnessFactory) -> None:
    harness = make_harness("streaming")
    harness.synth.fail_open = True
    voice_client = FakeVoiceClient()
    asyncio.run(_speak(harness, voice_client, "厳格"))
    assert harness.synth.generate_calls == []
    assert harness.playback.played == []


def test_auto_stops_retrying_streaming_after_repeated_failures(
    make_harness: HarnessFactory,
) -> None:
    harness = make_harness("auto")
    harness.synth.fail_open = True
    voice_client = FakeVoiceClient()

    async def scenario() -> None:
        for index in range(MAX_CONSECUTIVE_STREAMING_FAILURES + 2):
            await _speak(harness, voice_client, f"失敗{index}")

    asyncio.run(scenario())
    assert len(harness.synth.stream_calls) == MAX_CONSECUTIVE_STREAMING_FAILURES
    assert len(harness.synth.generate_calls) == MAX_CONSECUTIVE_STREAMING_FAILURES + 2


def test_success_resets_failure_count(make_harness: HarnessFactory) -> None:
    harness = make_harness("auto")
    voice_client = FakeVoiceClient()

    async def scenario() -> None:
        for _ in range(MAX_CONSECUTIVE_STREAMING_FAILURES - 1):
            harness.synth.fail_open = True
            await _speak(harness, voice_client, "失敗")
        harness.synth.fail_open = False
        await _speak(harness, voice_client, "成功")
        harness.synth.fail_open = True
        await _speak(harness, voice_client, "再失敗")
        harness.synth.fail_open = False
        await _speak(harness, voice_client, "継続")

    asyncio.run(scenario())
    assert harness.synth.stream_calls[-1] == "継続"


# --- cache ------------------------------------------------------------------------


def test_cache_hit_skips_synthesis_in_streaming_mode(make_harness: HarnessFactory) -> None:
    harness = make_harness("streaming")
    harness.synth.cache[("キャッシュ", 3)] = b"RIFF-cached"
    voice_client = FakeVoiceClient()
    asyncio.run(_speak(harness, voice_client, "キャッシュ"))
    assert harness.synth.stream_calls == []
    assert harness.synth.generate_calls == []
    assert harness.playback.played == [b"RIFF-cached"]


# --- skip / leave / reconnect / multi-guild --------------------------------------


def _blocked_harness(make_harness: HarnessFactory) -> tuple[Harness, threading.Event]:
    harness = make_harness("streaming", segments=6)
    gate = threading.Event()
    harness.synth.gates[3] = gate
    return harness, gate


def test_skip_cancels_synthesis_and_playback_then_continues(
    make_harness: HarnessFactory,
) -> None:
    harness, gate = _blocked_harness(make_harness)
    voice_client = FakeVoiceClient()
    guild = FakeGuild(1, voice_client)

    async def scenario() -> None:
        session = await harness.manager.open(1, voice_channel_id=10, text_channel_id=20)
        harness.manager.enqueue(session, SpeechItem(text="一つ目", speaker_id=3))
        harness.manager.ensure_worker(guild, session)  # pyright: ignore[reportArgumentType]
        assert await asyncio.to_thread(voice_client.play_started.wait, TIMEOUT)
        first_source = voice_client.sources[0]

        assert harness.manager.skip(1)
        await asyncio.sleep(0.05)
        assert first_source.read() == b""  # buffer discarded
        gate.set()  # producer thread wakes, sees the closed source and stops

        harness.synth.gates.clear()
        harness.manager.enqueue(session, SpeechItem(text="二つ目", speaker_id=3))
        await asyncio.wait_for(session.queue.join(), TIMEOUT)
        assert session.worker is not None
        assert not session.worker.done()
        await harness.manager.close(1)

    asyncio.run(scenario())
    voice_client.join()
    assert harness.synth.stream_calls == ["一つ目", "二つ目"]
    assert all(stream.closed for stream in harness.synth.streams)
    # The skipped stream stopped after the blocked segment instead of finishing.
    assert harness.synth.segments_produced <= 4 + 6


def test_skip_during_prebuffer_prevents_playback(make_harness: HarnessFactory) -> None:
    harness = make_harness("streaming", segments=4)
    gate = threading.Event()
    harness.synth.gates[1] = gate  # first segment only: still prebuffering
    voice_client = FakeVoiceClient()
    guild = FakeGuild(1, voice_client)

    async def scenario() -> None:
        session = await harness.manager.open(1, voice_channel_id=10, text_channel_id=20)
        harness.manager.enqueue(session, SpeechItem(text="スキップ", speaker_id=3))
        harness.manager.ensure_worker(guild, session)  # pyright: ignore[reportArgumentType]
        assert await asyncio.to_thread(harness.synth.segment_produced.wait, TIMEOUT)
        assert harness.manager.skip(1)
        await asyncio.sleep(0.05)
        gate.set()
        await asyncio.wait_for(session.queue.join(), TIMEOUT)
        await harness.manager.close(1)

    asyncio.run(scenario())
    assert voice_client.sources == []
    assert harness.synth.streams[0].closed


def test_leave_stops_streaming_and_releases_resources(make_harness: HarnessFactory) -> None:
    harness, gate = _blocked_harness(make_harness)
    voice_client = FakeVoiceClient()
    guild = FakeGuild(1, voice_client)

    async def scenario() -> None:
        session = await harness.manager.open(1, voice_channel_id=10, text_channel_id=20)
        harness.manager.enqueue(session, SpeechItem(text="退出", speaker_id=3))
        harness.manager.enqueue(session, SpeechItem(text="待機中", speaker_id=3))
        harness.manager.ensure_worker(guild, session)  # pyright: ignore[reportArgumentType]
        assert await asyncio.to_thread(voice_client.play_started.wait, TIMEOUT)
        current = session.current
        assert current is not None

        close_task = asyncio.create_task(harness.manager.close(1))
        await asyncio.sleep(0.05)
        gate.set()
        await asyncio.wait_for(close_task, TIMEOUT)

        assert harness.manager.get(1) is None
        assert current.done()
        assert session.worker is None
        assert session.queue.empty()

    asyncio.run(scenario())
    voice_client.join()
    assert harness.synth.stream_calls == ["退出"]
    assert harness.synth.streams[0].closed
    assert voice_client.sources[0].read() == b""


def test_reconnect_does_not_leak_previous_stream(make_harness: HarnessFactory) -> None:
    harness, gate = _blocked_harness(make_harness)
    old_client = FakeVoiceClient()
    new_client = FakeVoiceClient()
    guild = FakeGuild(1, old_client)

    async def scenario() -> None:
        old = await harness.manager.open(1, voice_channel_id=10, text_channel_id=20)
        harness.manager.enqueue(old, SpeechItem(text="旧セッション", speaker_id=3))
        harness.manager.ensure_worker(guild, old)  # pyright: ignore[reportArgumentType]
        assert await asyncio.to_thread(old_client.play_started.wait, TIMEOUT)

        open_task = asyncio.create_task(
            harness.manager.open(1, voice_channel_id=11, text_channel_id=21),
        )
        await asyncio.sleep(0.05)
        gate.set()
        new = await asyncio.wait_for(open_task, TIMEOUT)
        assert old.worker is None
        assert old.current is None or old.current.done()

        harness.synth.gates.clear()
        guild.voice_client = new_client
        harness.manager.enqueue(new, SpeechItem(text="新セッション", speaker_id=3))
        harness.manager.ensure_worker(guild, new)  # pyright: ignore[reportArgumentType]
        await asyncio.wait_for(new.queue.join(), TIMEOUT)
        await harness.manager.close(1)

    asyncio.run(scenario())
    old_client.join()
    new_client.join()
    # Nothing from the old session reached the new connection.
    assert len(new_client.sources) == 1
    assert len(_streamed_audio(new_client)) == 6 * SEGMENT_FRAMES * FRAME_SIZE


def test_multiple_guilds_stream_concurrently(make_harness: HarnessFactory) -> None:
    harness = make_harness("streaming", segments=4)
    clients = {guild_id: FakeVoiceClient() for guild_id in (1, 2, 3)}

    async def scenario() -> None:
        sessions = []
        for guild_id, client in clients.items():
            guild = FakeGuild(guild_id, client)
            session = await harness.manager.open(guild_id, guild_id * 10, guild_id * 100)
            harness.manager.enqueue(session, SpeechItem(text=f"ギルド{guild_id}", speaker_id=3))
            harness.manager.ensure_worker(guild, session)  # pyright: ignore[reportArgumentType]
            sessions.append(session)
        await asyncio.wait_for(
            asyncio.gather(*(session.queue.join() for session in sessions)),
            TIMEOUT,
        )
        await harness.manager.close_all()

    asyncio.run(scenario())
    for client in clients.values():
        client.join()
        assert len(client.sources) == 1
        assert len(_streamed_audio(client)) == 4 * SEGMENT_FRAMES * FRAME_SIZE
    assert sorted(harness.synth.stream_calls) == ["ギルド1", "ギルド2", "ギルド3"]


def test_synthesizer_without_streaming_api_uses_normal(make_harness: HarnessFactory) -> None:
    """A synthesizer lacking the streaming API (e.g. older fakes) keeps working in auto mode."""

    class PlainSynthesizer:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def generate(self, text: str, speaker_id: int | None = None) -> bytes:  # noqa: ARG002
            self.calls.append(text)
            return b"wav"

        def is_style_available(self, style_id: int) -> bool:  # noqa: ARG002
            return True

        def available_style_ids(self) -> frozenset[int]:
            return frozenset({3})

    harness = make_harness("auto")
    plain = PlainSynthesizer()
    manager = SessionManager(
        replace(harness.settings, synthesis_mode="auto"),
        harness.database,
        IdentityTranslator(harness.database),
        plain,
    )
    manager._play_wav_data = harness.playback  # pyright: ignore[reportAttributeAccessIssue]
    voice_client = FakeVoiceClient()

    asyncio.run(
        asyncio.wait_for(
            manager._speak_one(FakeGuild(1, voice_client), SpeechItem("通常", 3)),  # pyright: ignore[reportArgumentType]
            TIMEOUT,
        ),
    )
    assert plain.calls == ["通常"]
    assert harness.playback.played == [b"wav"]
