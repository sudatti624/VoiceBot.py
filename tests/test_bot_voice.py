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
    def __init__(
        self,
        member_id: int,
        channel: FakeVoiceChannel | None,
        *,
        bot: bool = False,
        display_name: str = "member",
    ) -> None:
        self.id = member_id
        self.bot = bot
        self.display_name = display_name
        self.voice = None if channel is None else FakeVoiceState(channel)


class FakeGuild:
    def __init__(self, guild_id: int, voice_client: object | None = None) -> None:
        self.id = guild_id
        self.voice_client = voice_client
        self.voice_state_changes: list[dict[str, object]] = []

    async def change_voice_state(self, **kwargs: object) -> None:
        self.voice_state_changes.append(kwargs)


class FakeTextChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id


class FakeMessage:
    def __init__(
        self,
        *,
        content: str,
        author: FakeMember,
        guild: FakeGuild,
        channel: FakeTextChannel,
    ) -> None:
        self.content = content
        self.author = author
        self.guild = guild
        self.channel = channel
        self.attachments: list[object] = []
        self.mentions: list[object] = []
        self.replies: list[str] = []

    async def reply(self, content: str) -> None:
        self.replies.append(content)


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


def test_on_message_reads_other_bot_messages(tmp_path: Path) -> None:
    async def scenario() -> None:
        bot = make_bot(tmp_path)
        guild = FakeGuild(1)
        text_channel = FakeTextChannel(20)
        author = FakeMember(200, None, bot=True, display_name="OtherBot")
        message = FakeMessage(
            content="BOTからの通知です",
            author=author,
            guild=guild,
            channel=text_channel,
        )
        session = await bot.session_manager.open(
            guild.id,
            voice_channel_id=10,
            text_channel_id=text_channel.id,
        )
        bot.session_manager.ensure_worker = lambda _guild, _session: None

        try:
            await bot.on_message(message)

            item = session.queue.get_nowait()
            assert item.text == "OtherBot、BOTからの通知です"
            assert item.speaker_id == bot.settings.speaker_id
            assert message.replies == []
        finally:
            await bot.close()

    asyncio.run(scenario())


def test_on_message_ignores_own_messages(tmp_path: Path) -> None:
    async def scenario() -> None:
        bot = make_bot(tmp_path)
        guild = FakeGuild(1)
        text_channel = FakeTextChannel(20)
        author = FakeMember(100, None, bot=True, display_name="Yomiage")
        message = FakeMessage(
            content="自分の返信です",
            author=author,
            guild=guild,
            channel=text_channel,
        )
        session = await bot.session_manager.open(
            guild.id,
            voice_channel_id=10,
            text_channel_id=text_channel.id,
        )
        bot._is_own_message = lambda _message: True

        try:
            await bot.on_message(message)

            assert session.queue.empty()
        finally:
            await bot.close()

    asyncio.run(scenario())


def test_prepare_message_strips_server_chat_prefix_when_enabled(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    guild = FakeGuild(1)
    text_channel = FakeTextChannel(20)
    author = FakeMember(200, None, display_name="DiscordUser")
    message = FakeMessage(
        content="[world]<MinecraftUser> こんにちは",
        author=author,
        guild=guild,
        channel=text_channel,
    )
    bot.database.set_server_chat_enabled(
        guild.id,
        bot.settings.bot_id,
        enabled=True,
        fallback_speaker_id=bot.settings.speaker_id,
    )

    try:
        assert bot._prepare_message_text(message) == "DiscordUser、こんにちは"
    finally:
        asyncio.run(bot.close())


def test_prepare_message_keeps_server_chat_prefix_when_disabled(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    guild = FakeGuild(1)
    text_channel = FakeTextChannel(20)
    author = FakeMember(200, None, display_name="DiscordUser")
    message = FakeMessage(
        content="[world]<MinecraftUser> こんにちは",
        author=author,
        guild=guild,
        channel=text_channel,
    )

    try:
        expected = "DiscordUser、[world]<MinecraftUser> こんにちは"
        assert bot._prepare_message_text(message) == expected
    finally:
        asyncio.run(bot.close())


def test_prepare_message_replaces_custom_emoji_with_name(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    guild = FakeGuild(1)
    text_channel = FakeTextChannel(20)
    author = FakeMember(200, None, display_name="DiscordUser")
    message = FakeMessage(
        content="いいね <:kusa:123456789012345678> <a:party:987654321098765432>",
        author=author,
        guild=guild,
        channel=text_channel,
    )

    try:
        assert bot._prepare_message_text(message) == "DiscordUser、いいね kusa party"
    finally:
        asyncio.run(bot.close())
