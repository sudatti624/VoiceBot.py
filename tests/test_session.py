from __future__ import annotations

import asyncio
from pathlib import Path
from types import MethodType

import pytest

from yomiage.config import Settings
from yomiage.database import Database
from yomiage.speech import SessionManager, SpeechItem
from yomiage.translator import Translator


class FakeGuild:
    """Minimal stand-in for discord.Guild.

    The worker task only touches ``guild.voice_client`` once an item has been
    dequeued, so an empty-queue lifecycle test never needs a real Discord
    connection.
    """

    def __init__(self, guild_id: int) -> None:
        self.id = guild_id


class FakeSynthesizer:
    def generate(self, text: str, speaker_id: int | None = None) -> bytes:  # noqa: ARG002
        return b""

    def is_style_available(self, style_id: int) -> bool:  # noqa: ARG002
        return True

    def available_style_ids(self) -> frozenset[int]:
        return frozenset({0, 1, 2, 3})


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        discord_token="test-token",  # noqa: S106 - test fixture, not a real secret
        bot_id=0,
        database_path=tmp_path / "test.sqlite3",
        max_tokens=400,
        speaker_id=3,
        speed=1.2,
        voicevox_onnxruntime_path=tmp_path / "onnxruntime",
        open_jtalk_dict_dir=tmp_path / "dict",
        voicevox_model_path=tmp_path / "model.vvm",
        voicevox_acceleration_mode="CPU",
        cache_size=10,
        ffmpeg_path="ffmpeg",
    )


@pytest.fixture
def session_manager(tmp_path: Path) -> SessionManager:
    settings = _make_settings(tmp_path)
    database = Database(settings.database_path)
    translator = Translator(database)
    manager = SessionManager(settings, database, translator, FakeSynthesizer())
    yield manager
    database.close()


def test_rejoin_shuts_down_previous_worker(session_manager: SessionManager) -> None:
    async def scenario() -> None:
        guild = FakeGuild(guild_id=1)

        session1 = await session_manager.open(guild.id, voice_channel_id=10, text_channel_id=20)
        session_manager.ensure_worker(guild, session1)
        worker1 = session1.worker
        assert worker1 is not None
        await asyncio.sleep(0)
        assert not worker1.done()

        session2 = await session_manager.open(guild.id, voice_channel_id=11, text_channel_id=21)
        await asyncio.sleep(0)

        assert worker1.done()
        assert session2 is not session1
        assert session_manager.get(guild.id) is session2
        assert session_manager.get(guild.id).text_channel_id == 21

    asyncio.run(scenario())


def test_worker_continues_after_item_error(session_manager: SessionManager) -> None:
    async def scenario() -> None:
        guild = FakeGuild(guild_id=4)
        session = await session_manager.open(guild.id, voice_channel_id=10, text_channel_id=20)
        calls: list[str] = []

        async def speak_one(
            _manager: SessionManager,
            _guild: FakeGuild,
            item: SpeechItem,
        ) -> None:
            calls.append(item.text)
            if item.text == "fail":
                raise RuntimeError("test failure")

        session_manager._speak_one = MethodType(speak_one, session_manager)
        assert session_manager.enqueue(session, SpeechItem(text="fail", speaker_id=3))
        assert session_manager.enqueue(session, SpeechItem(text="next", speaker_id=3))
        session_manager.ensure_worker(guild, session)

        await asyncio.wait_for(session.queue.join(), timeout=1.0)

        assert calls == ["fail", "next"]
        assert session.worker is not None
        assert not session.worker.done()
        await session_manager.close(guild.id)

    asyncio.run(scenario())


def test_close_cancels_worker_and_drains_queue(session_manager: SessionManager) -> None:
    async def scenario() -> None:
        guild = FakeGuild(guild_id=2)
        session = await session_manager.open(guild.id, voice_channel_id=10, text_channel_id=20)
        session_manager.enqueue(session, SpeechItem(text="hello", speaker_id=3))
        session_manager.ensure_worker(guild, session)
        worker = session.worker
        assert worker is not None
        await asyncio.sleep(0)

        await session_manager.close(guild.id)

        assert worker.done()
        assert session_manager.get(guild.id) is None
        assert session.queue.empty()

    asyncio.run(scenario())


def test_close_all_shuts_down_every_guild(session_manager: SessionManager) -> None:
    async def scenario() -> None:
        guild_a = FakeGuild(guild_id=1)
        guild_b = FakeGuild(guild_id=2)
        session_a = await session_manager.open(guild_a.id, voice_channel_id=1, text_channel_id=1)
        session_b = await session_manager.open(guild_b.id, voice_channel_id=2, text_channel_id=2)
        session_manager.ensure_worker(guild_a, session_a)
        session_manager.ensure_worker(guild_b, session_b)
        worker_a = session_a.worker
        worker_b = session_b.worker
        assert worker_a is not None
        assert worker_b is not None
        await asyncio.sleep(0)

        await session_manager.close_all()

        assert session_manager.get(guild_a.id) is None
        assert session_manager.get(guild_b.id) is None
        assert worker_a.done()
        assert worker_b.done()

    asyncio.run(scenario())


def test_enqueue_rejects_when_queue_full(session_manager: SessionManager) -> None:
    async def scenario() -> None:
        guild = FakeGuild(guild_id=3)
        session = await session_manager.open(guild.id, voice_channel_id=10, text_channel_id=20)
        for _ in range(session.queue.maxsize):
            assert session_manager.enqueue(session, SpeechItem(text="x", speaker_id=3))
        assert not session_manager.enqueue(session, SpeechItem(text="overflow", speaker_id=3))

    asyncio.run(scenario())
