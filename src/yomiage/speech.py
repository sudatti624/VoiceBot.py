"""Per-guild voice session lifecycle: connect, queue, playback, and teardown.

Every guild has at most one :class:`GuildSession` at a time. All creation and
teardown must go through :class:`SessionManager` so join, leave, automatic
disconnect, re-join, bot shutdown, and an unexpected VC disconnect all follow
the exact same cleanup path (cancel worker, drain queue). This avoids stale
sessions and leaked worker tasks.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from io import BytesIO

import discord

from yomiage.config import Settings
from yomiage.database import Database
from yomiage.rate_limit import TokenBucket
from yomiage.translator import Translator
from yomiage.voicevox import SynthesizerLike

LOGGER = logging.getLogger(__name__)

MAX_QUEUE_SIZE = 50
TOKEN_REFILL_AMOUNT = 50
TOKEN_REFILL_INTERVAL_SECONDS = 10.0


@dataclass(frozen=True)
class SpeechItem:
    text: str
    speaker_id: int


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

    async def shutdown(self) -> None:
        """Cancel the worker task and drop any queued speech. Safe to call twice."""
        while not self.queue.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
                self.queue.task_done()

        worker = self.worker
        self.worker = None
        if worker is None or worker.done() or worker is asyncio.current_task():
            return
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker


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

    def ensure_worker(self, guild: discord.Guild, session: GuildSession) -> None:
        if session.worker is None or session.worker.done():
            session.worker = asyncio.create_task(self._speak_worker(guild, session))

    async def _speak_worker(self, guild: discord.Guild, session: GuildSession) -> None:
        while True:
            item = await session.queue.get()
            try:
                await self._speak_one(guild, item)
            except asyncio.CancelledError:
                session.queue.task_done()
                raise
            except Exception:
                LOGGER.exception("Speech item failed unexpectedly for guild=%s", guild.id)
                session.queue.task_done()
            else:
                session.queue.task_done()

    async def _speak_one(self, guild: discord.Guild, item: SpeechItem) -> None:
        voice_client = guild.voice_client
        if not isinstance(voice_client, discord.VoiceClient):
            return

        converted = self.translator.convert(item.text, guild.id, self.settings.bot_id)
        if not converted.strip():
            return

        try:
            wav_data = await asyncio.to_thread(
                self.synthesizer.generate,
                converted,
                item.speaker_id,
            )
        except Exception:
            LOGGER.exception("VOICEVOX synthesis failed for guild=%s", guild.id)
            return

        try:
            await self._play_wav_data(voice_client, wav_data)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Playback failed for guild=%s", guild.id)

    async def _play_wav_data(
        self,
        voice_client: discord.VoiceClient,
        wav_data: bytes,
    ) -> None:
        loop = asyncio.get_running_loop()
        finished = asyncio.Event()

        def on_finished(error: Exception | None) -> None:
            if error is not None:
                LOGGER.warning("Discord playback failed: %s", error)
            loop.call_soon_threadsafe(finished.set)

        source = discord.FFmpegPCMAudio(
            source=BytesIO(wav_data),
            executable=self.settings.ffmpeg_path,
            pipe=True,
        )
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
