"""Per-guild voice session lifecycle: connect, queue, playback, and teardown.

Every guild has at most one :class:`GuildSession` at a time. All creation and
teardown must go through :class:`SessionManager` so join, leave, automatic
disconnect, re-join, bot shutdown, and an unexpected VC disconnect all follow
the exact same cleanup path (cancel worker, drain queue). This avoids stale
sessions and leaked worker tasks.

Each speech item runs as its own task (``GuildSession.current``) so ``/skip`` can
cancel synthesis and playback of just that item. In ``streaming``/``auto`` mode,
synthesis runs in a worker thread that feeds a :class:`StreamingPCMSource`
while Discord is already playing it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from io import BytesIO

import discord

from yomiage.audio_stream import ObservedSource, PcmConverter, StreamingPCMSource
from yomiage.config import Settings, VoicevoxSynthesisMode
from yomiage.database import Database
from yomiage.perf import SpeechMetrics
from yomiage.rate_limit import TokenBucket
from yomiage.translator import Translator, has_speakable_content
from yomiage.voicevox import StreamingSynthesizerLike, SynthesizerLike

LOGGER = logging.getLogger(__name__)

MAX_QUEUE_SIZE = 50
TOKEN_REFILL_AMOUNT = 50
TOKEN_REFILL_INTERVAL_SECONDS = 10.0
# Lower bound for the streaming buffer cap; the effective cap also leaves room for
# the prebuffer plus two segments so the producer can always make progress.
STREAM_MAX_BUFFER_FLOOR_SECONDS = 2.0
# How long teardown waits for the synthesis thread to notice the source was closed.
# It stops after at most one segment, so this only matters if the lock is contended.
PRODUCER_JOIN_TIMEOUT_SECONDS = 10.0
# ``auto`` mode stops trying streaming for a style after this many consecutive
# runtime failures (until restart) so a broken model cannot cause endless retries.
MAX_CONSECUTIVE_STREAMING_FAILURES = 3


@dataclass(frozen=True)
class SpeechItem:
    text: str
    speaker_id: int


class StreamingStartError(RuntimeError):
    """Streaming failed before any audio reached Discord, so a fallback is safe."""


@dataclass
class GuildSession:
    guild_id: int
    voice_channel_id: int
    text_channel_id: int
    token_bucket: TokenBucket
    queue: asyncio.Queue[SpeechItem] = field(
        default_factory=lambda: asyncio.Queue(maxsize=MAX_QUEUE_SIZE),
    )
    worker: asyncio.Task[None] | None = None
    current: asyncio.Task[None] | None = None

    def skip_current(self) -> bool:
        """Cancel synthesis and playback of the item being spoken, if any."""
        task = self.current
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def shutdown(self) -> None:
        """Cancel the worker task and drop any queued speech. Safe to call twice."""
        while not self.queue.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
                self.queue.task_done()

        worker = self.worker
        self.worker = None
        current = self.current
        if worker is not None and not worker.done() and worker is not asyncio.current_task():
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        # The worker cancels its current item, but make sure even if it was never awaited.
        if current is not None and not current.done() and current is not asyncio.current_task():
            current.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await current


class StreamingPolicy:
    """Decides per style whether to stream, shared by every guild (global mode)."""

    def __init__(self, mode: VoicevoxSynthesisMode, synthesizer: SynthesizerLike) -> None:
        self.mode = mode
        self._synthesizer = (
            synthesizer if isinstance(synthesizer, StreamingSynthesizerLike) else None
        )
        self._failures: dict[int, int] = {}
        self._disabled: set[int] = set()
        self._warned_unsupported: set[int] = set()

    @property
    def streaming_synthesizer(self) -> StreamingSynthesizerLike | None:
        return self._synthesizer

    def should_stream(self, style_id: int) -> bool:
        if self.mode == "normal" or self._synthesizer is None or style_id in self._disabled:
            return False
        if self._synthesizer.supports_streaming(style_id):
            return True
        if style_id not in self._warned_unsupported:
            self._warned_unsupported.add(style_id)
            log = LOGGER.warning if self.mode == "streaming" else LOGGER.info
            log(
                "VOICEVOX style %s does not support streaming (old-format VVM?); "
                "using normal synthesis for it",
                style_id,
            )
        return False

    def allows_fallback(self) -> bool:
        return self.mode == "auto"

    def record_success(self, style_id: int) -> None:
        self._failures.pop(style_id, None)

    def record_failure(self, style_id: int) -> None:
        if self.mode != "auto":
            return
        count = self._failures.get(style_id, 0) + 1
        self._failures[style_id] = count
        if count >= MAX_CONSECUTIVE_STREAMING_FAILURES and style_id not in self._disabled:
            self._disabled.add(style_id)
            LOGGER.warning(
                "Streaming failed %s times in a row for style %s; "
                "using normal synthesis for it until restart",
                count,
                style_id,
            )


class SessionManager:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        translator: Translator,
        synthesizer: SynthesizerLike,
    ) -> None:
        self.settings = settings
        self.database = database
        self.translator = translator
        self.synthesizer = synthesizer
        self.streaming_policy = StreamingPolicy(settings.synthesis_mode, synthesizer)
        self._sessions: dict[int, GuildSession] = {}

    def get(self, guild_id: int) -> GuildSession | None:
        return self._sessions.get(guild_id)

    async def open(
        self,
        guild_id: int,
        voice_channel_id: int,
        text_channel_id: int,
    ) -> GuildSession:
        """Create the session for a guild, shutting down any previous one first.

        This is the single place a re-join (via ``/join`` or a mention) goes
        through, so the old worker task and queue can never leak.
        """
        await self.close(guild_id)
        session = GuildSession(
            guild_id=guild_id,
            voice_channel_id=voice_channel_id,
            text_channel_id=text_channel_id,
            token_bucket=TokenBucket(
                capacity=self.settings.max_tokens,
                refill_amount=TOKEN_REFILL_AMOUNT,
                refill_interval=TOKEN_REFILL_INTERVAL_SECONDS,
            ),
        )
        self._sessions[guild_id] = session
        return session

    async def close(self, guild_id: int) -> None:
        session = self._sessions.pop(guild_id, None)
        if session is not None:
            await session.shutdown()

    async def close_all(self) -> None:
        for guild_id in tuple(self._sessions):
            await self.close(guild_id)

    def enqueue(self, session: GuildSession, item: SpeechItem) -> bool:
        try:
            session.queue.put_nowait(item)
        except asyncio.QueueFull:
            return False
        return True

    def skip(self, guild_id: int) -> bool:
        session = self._sessions.get(guild_id)
        return session is not None and session.skip_current()

    def ensure_worker(self, guild: discord.Guild, session: GuildSession) -> None:
        if session.worker is None or session.worker.done():
            session.worker = asyncio.create_task(self._speak_worker(guild, session))

    async def _speak_worker(self, guild: discord.Guild, session: GuildSession) -> None:
        while True:
            item = await session.queue.get()
            try:
                await self._run_item(guild, session, item)
            finally:
                session.queue.task_done()

    async def _run_item(
        self,
        guild: discord.Guild,
        session: GuildSession,
        item: SpeechItem,
    ) -> None:
        task = asyncio.create_task(self._speak_one(guild, item))
        session.current = task
        try:
            await task
        except asyncio.CancelledError:
            worker = asyncio.current_task()
            if worker is not None and worker.cancelling():
                # The worker itself is shutting down: make sure the item is gone too.
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                raise
            LOGGER.info("Speech item skipped for guild=%s", guild.id)
        except Exception:
            LOGGER.exception("Speech item failed unexpectedly for guild=%s", guild.id)
        finally:
            if session.current is task:
                session.current = None

    async def _speak_one(self, guild: discord.Guild, item: SpeechItem) -> None:
        voice_client = guild.voice_client
        if not isinstance(voice_client, discord.VoiceClient):
            return

        converted = self.translator.convert(item.text, guild.id, self.settings.bot_id)
        if not converted.strip() or not has_speakable_content(converted):
            return

        metrics = SpeechMetrics(guild_id=guild.id, configured_mode=self.settings.synthesis_mode)
        try:
            await self._speak_text(voice_client, converted, item.speaker_id, metrics)
        except asyncio.CancelledError:
            metrics.outcome = "cancelled"
            raise
        finally:
            if self.settings.performance_log:
                metrics.log()

    async def _speak_text(
        self,
        voice_client: discord.VoiceClient,
        text: str,
        speaker_id: int,
        metrics: SpeechMetrics,
    ) -> None:
        policy = self.streaming_policy
        streaming_synthesizer = policy.streaming_synthesizer
        if streaming_synthesizer is not None:
            cached = await asyncio.to_thread(streaming_synthesizer.get_cached, text, speaker_id)
            metrics.cache_hit = cached is not None
            if cached is not None:
                metrics.path = "cache"
                await self._play_and_log(voice_client, cached, metrics)
                return

        if policy.should_stream(speaker_id):
            assert streaming_synthesizer is not None  # noqa: S101 - implied by should_stream
            metrics.path = "streaming"
            try:
                await self._play_streaming(
                    voice_client,
                    streaming_synthesizer,
                    text,
                    speaker_id,
                    metrics,
                )
            except StreamingStartError as exc:
                policy.record_failure(speaker_id)
                if not policy.allows_fallback():
                    LOGGER.error(  # noqa: TRY400 - cause is logged with exc_info below
                        "Streaming synthesis failed for guild=%s style=%s",
                        metrics.guild_id,
                        speaker_id,
                        exc_info=exc.__cause__,
                    )
                    metrics.outcome = "failed"
                    return
                LOGGER.warning(
                    "Streaming synthesis failed before playback for guild=%s style=%s; "
                    "falling back to normal synthesis",
                    metrics.guild_id,
                    speaker_id,
                    exc_info=exc.__cause__,
                )
                metrics.path = "streaming->normal"
                metrics.synthesis_started_at = None
                metrics.first_audio_at = None
                metrics.synthesis_finished_at = None
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Streaming playback failed for guild=%s", metrics.guild_id)
                metrics.outcome = "failed"
                return
            else:
                return

        await self._speak_normal(voice_client, text, speaker_id, metrics)

    async def _speak_normal(
        self,
        voice_client: discord.VoiceClient,
        text: str,
        speaker_id: int,
        metrics: SpeechMetrics,
    ) -> None:
        def generate() -> bytes:
            metrics.synthesis_started_at = time.perf_counter()
            wav = self.synthesizer.generate(text, speaker_id)
            metrics.synthesis_finished_at = metrics.first_audio_at = time.perf_counter()
            return wav

        try:
            wav_data = await asyncio.to_thread(generate)
        except Exception:
            LOGGER.exception("VOICEVOX synthesis failed for guild=%s", metrics.guild_id)
            metrics.outcome = "failed"
            return

        await self._play_and_log(voice_client, wav_data, metrics)

    async def _play_and_log(
        self,
        voice_client: discord.VoiceClient,
        wav_data: bytes,
        metrics: SpeechMetrics,
    ) -> None:
        try:
            await self._play_wav_data(
                voice_client,
                wav_data,
                metrics if self.settings.performance_log else None,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Playback failed for guild=%s", metrics.guild_id)
            metrics.outcome = "failed"

    async def _play_wav_data(
        self,
        voice_client: discord.VoiceClient,
        wav_data: bytes,
        metrics: SpeechMetrics | None = None,
    ) -> None:
        loop = asyncio.get_running_loop()
        finished = asyncio.Event()

        def on_finished(error: Exception | None) -> None:
            if error is not None:
                LOGGER.warning("Discord playback failed: %s", error)
            if metrics is not None:
                metrics.playback_finished_at = time.perf_counter()
            with contextlib.suppress(RuntimeError):  # loop already closed at shutdown
                loop.call_soon_threadsafe(finished.set)

        source: discord.AudioSource = discord.FFmpegPCMAudio(
            source=BytesIO(wav_data),
            executable=self.settings.ffmpeg_path,
            pipe=True,
        )
        observed = ObservedSource(source) if metrics is not None else None
        if observed is not None:
            source = observed
        try:
            voice_client.play(source, after=on_finished)
            await finished.wait()
        except asyncio.CancelledError:
            voice_client.stop()
            source.cleanup()
            raise
        except Exception:
            source.cleanup()
            raise
        finally:
            if metrics is not None and observed is not None:
                metrics.playback_started_at = observed.first_read_at

    async def _play_streaming(
        self,
        voice_client: discord.VoiceClient,
        synthesizer: StreamingSynthesizerLike,
        text: str,
        speaker_id: int,
        metrics: SpeechMetrics,
    ) -> None:
        """Play while synthesizing. Never collects the whole utterance before playing.

        Raises :class:`StreamingStartError` if synthesis fails before
        ``voice_client.play`` was called; after that point errors are only logged,
        because falling back would read the message twice.
        """
        loop = asyncio.get_running_loop()
        ready = asyncio.Event()
        finished = asyncio.Event()

        def signal(event: asyncio.Event) -> None:
            with contextlib.suppress(RuntimeError):  # loop already closed at shutdown
                loop.call_soon_threadsafe(event.set)

        source = StreamingPCMSource(
            prebuffer_seconds=self.settings.stream_buffer_seconds,
            max_buffer_seconds=max(
                STREAM_MAX_BUFFER_FLOOR_SECONDS,
                self.settings.stream_buffer_seconds + 2 * self.settings.stream_segment_seconds,
            ),
            on_ready=lambda: signal(ready),
        )
        producer = asyncio.create_task(
            asyncio.to_thread(self._produce_stream, synthesizer, text, speaker_id, source, metrics),
        )
        started = False
        try:
            # Ready = prebuffer filled, or synthesis ended (short text / error).
            await ready.wait()
            if source.error is not None:
                raise StreamingStartError("streaming synthesis failed") from source.error
            if source.bytes_written == 0:
                return

            def on_finished(error: Exception | None) -> None:
                if error is not None:
                    LOGGER.warning("Discord streaming playback failed: %s", error)
                metrics.playback_finished_at = time.perf_counter()
                signal(finished)

            voice_client.play(source, after=on_finished)
            started = True
            await finished.wait()
        except asyncio.CancelledError:
            if started:
                voice_client.stop()
            raise
        finally:
            source.close()
            await self._join_producer(producer, metrics.guild_id)
            metrics.playback_started_at = source.first_read_at
            metrics.underruns = source.underruns if started else None

        if source.error is not None:
            # Audio already reached Discord: no fallback, or the text would be read twice.
            LOGGER.error(
                "Streaming synthesis failed mid-playback for guild=%s style=%s",
                metrics.guild_id,
                speaker_id,
                exc_info=source.error,
            )
            self.streaming_policy.record_failure(speaker_id)
            metrics.outcome = "failed"
            return
        self.streaming_policy.record_success(speaker_id)

    @staticmethod
    def _produce_stream(
        synthesizer: StreamingSynthesizerLike,
        text: str,
        speaker_id: int,
        source: StreamingPCMSource,
        metrics: SpeechMetrics,
    ) -> None:
        """Synthesis thread: pull segments, convert to Discord PCM, push into the source.

        ``source.write`` blocks while the buffer is full (backpressure); since
        VOICEVOX only synthesizes when the next segment is requested, that also
        pauses synthesis. It returns ``False`` once the source is closed (skip,
        leave, shutdown), which ends synthesis after the current segment.
        """
        error: BaseException | None = None
        try:
            metrics.synthesis_started_at = time.perf_counter()
            with synthesizer.open_stream(text, speaker_id) as stream:
                converter = PcmConverter(stream.format.sample_rate, stream.format.channels)
                for pcm in stream:
                    if metrics.first_audio_at is None:
                        metrics.first_audio_at = time.perf_counter()
                    if not source.write(converter.feed(pcm)):
                        return
                metrics.synthesis_finished_at = time.perf_counter()
                source.write(converter.flush())
        except Exception as exc:  # noqa: BLE001 - reported through the source to the event loop
            error = exc
        finally:
            source.finish(error)

    @staticmethod
    async def _join_producer(producer: asyncio.Task[None], guild_id: int) -> None:
        if not producer.done():
            await asyncio.wait({producer}, timeout=PRODUCER_JOIN_TIMEOUT_SECONDS)
        if not producer.done():
            LOGGER.warning(
                "Streaming synthesis thread for guild=%s did not stop within %.0fs",
                guild_id,
                PRODUCER_JOIN_TIMEOUT_SECONDS,
            )
            return
        if not producer.cancelled() and producer.exception() is not None:
            LOGGER.error(
                "Streaming producer crashed for guild=%s",
                guild_id,
                exc_info=producer.exception(),
            )
