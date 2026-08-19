from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import yomiage.bot as bot_module
from yomiage.bot import YomiageBot
from yomiage.config import Settings
from yomiage.database import Database
from yomiage.translator import Translator


class FakeSynthesizer:
    def generate(self, text: str, speaker_id: int | None = None) -> bytes:  # noqa: ARG002
        return b""

    def is_style_available(self, style_id: int) -> bool:  # noqa: ARG002
        return True

    def available_style_ids(self) -> frozenset[int]:
        return frozenset({0, 1, 2, 3})


class FakeVoiceChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id
        self.mention = f"<#{channel_id}>"
        self.connect_kwargs: dict[str, object] | None = None

    async def connect(self, **kwargs: object) -> FakeVoiceClient:
        self.connect_kwargs = kwargs
        return FakeVoiceClient(self)


class FakeVoiceClient:
    def __init__(self, channel: FakeVoiceChannel) -> None:
        self.channel = channel
        self.moved_to: FakeVoiceChannel | None = None

    async def move_to(self, channel: FakeVoiceChannel) -> None:
        self.moved_to = channel
        self.channel = channel


class FakeVoiceState:
    def __init__(self, channel: FakeVoiceChannel) -> None:
        self.channel = channel


class FakeMember:
    def __init__(self, member_id: int, channel: FakeVoiceChannel) -> None:
        self.id = member_id
        self.voice = FakeVoiceState(channel)


class FakeGuild:
    def __init__(self, guild_id: int, voice_client: object | None = None) -> None:
        self.id = guild_id
        self.voice_client = voice_client
        self.voice_state_changes: list[dict[str, object]] = []

    async def change_voice_state(self, **kwargs: object) -> None:
        self.voice_state_changes.append(kwargs)


def make_bot(tmp_path: Path) -> YomiageBot:
    settings = Settings(
        discord_token="test-token",  # noqa: S106
        bot_id=0,
        database_path=tmp_path / "test.sqlite3",
        max_tokens=400,
        speaker_id=3,
        speed=1.2,
        voicevox_onnxruntime_path=tmp_path / "onnxruntime",
        open_jtalk_dict_dir=tmp_path / "dict",
        voicevox_model_path=tmp_path / "model.vvm",
        cache_size=10,
        ffmpeg_path="ffmpeg",
    )
    database = Database(settings.database_path)
    return YomiageBot(settings, database, Translator(database), FakeSynthesizer())


def test_join_connects_with_self_deaf(tmp_path: Path) -> None:
    async def scenario() -> None:
        bot = make_bot(tmp_path)
        channel = FakeVoiceChannel(10)
        guild = FakeGuild(1)
        member = FakeMember(100, channel)

        try:
            reply = await bot._join_member_voice(guild, member, text_channel_id=20)

            assert channel.connect_kwargs is not None
            assert channel.connect_kwargs["self_deaf"] is True
            assert bot.session_manager.get(guild.id) is not None
            assert reply == "<#10> に接続しました"
        finally:
            await bot.close()

    asyncio.run(scenario())


def test_rejoin_move_keeps_self_deaf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        bot = make_bot(tmp_path)
        old_channel = FakeVoiceChannel(10)
        new_channel = FakeVoiceChannel(11)
        voice_client = FakeVoiceClient(old_channel)
        guild = FakeGuild(1, voice_client=voice_client)
        member = FakeMember(100, new_channel)
        monkeypatch.setattr(bot_module.discord, "VoiceClient", FakeVoiceClient)

        try:
            reply = await bot._join_member_voice(guild, member, text_channel_id=20)

            assert voice_client.moved_to is new_channel
            assert guild.voice_state_changes == [{"channel": new_channel, "self_deaf": True}]
            assert new_channel.connect_kwargs is None
            assert reply == "<#11> に移動しました"
        finally:
            await bot.close()

    asyncio.run(scenario())
