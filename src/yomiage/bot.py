from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from typing import cast

import discord
from discord import app_commands

from yomiage.config import Settings
from yomiage.database import Database
from yomiage.translator import Translator
from yomiage.voicevox import VoicevoxSynthesizer

LOGGER = logging.getLogger(__name__)
REFILL_RATE = 50
REFILL_INTERVAL_SECONDS = 10
MAX_MESSAGE_LENGTH = 80
MAX_DICT_ENTRIES = 27
MAX_DICT_WORD_LENGTH = 120
MAX_DICT_READING_LENGTH = 80
MAX_QUEUE_SIZE = 50
SKIP_SHORTCUTS = frozenset({"s", "S", "!s", "!S", "！s", "！S"})
MENTION_PATTERN = re.compile(r"<(@!?|@&|#)(\d+)>")
DISCORD_CHANNEL_URL_PATTERN = re.compile(
    r"https?://(?:canary\.|ptb\.)?discord(?:app)?\.com/channels/(\d+|@me)/(\d+)(?:/\d+)?",
)
NESTED_QUANTIFIER_PATTERN = re.compile(r"\((?:[^()\\]|\\.)*[*+](?:[^()\\]|\\.)*\)[*+{]")


@dataclass(frozen=True)
class SpeechItem:
    text: str
    speaker_id: int


@dataclass
class GuildSession:
    voice_channel_id: int
    text_channel_id: int
    tokens: int
    last_token_refill: datetime = field(default_factory=lambda: datetime.now(UTC))
    queue: asyncio.Queue[SpeechItem] = field(
        default_factory=lambda: asyncio.Queue(maxsize=MAX_QUEUE_SIZE),
    )
    worker: asyncio.Task[None] | None = None


class YomiageBot(discord.Client):
    def __init__(
        self,
        settings: Settings,
        database: Database,
        translator: Translator,
        synthesizer: VoicevoxSynthesizer,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        super().__init__(intents=intents)
        self.settings = settings
        self.database = database
        self.translator = translator
        self.synthesizer = synthesizer
        self.tree = app_commands.CommandTree(self)
        self.sessions: dict[int, GuildSession] = {}
        self._register_commands()

    async def setup_hook(self) -> None:
        await self.tree.sync()

    async def on_ready(self) -> None:
        user = self.user
        if user is not None:
            LOGGER.info("Bot ready: %s (%s)", user, user.id)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild or not message.content:
            return

        if self._is_bot_mentioned(message):
            await self._join_from_message(message)
            return

        session = self.sessions.get(message.guild.id)
        if session is None or message.channel.id != session.text_channel_id:
            return

        if message.content.strip() in SKIP_SHORTCUTS:
            self._skip_guild(message.guild)
            return

        if not self._consume_token(message.guild.id, message.content):
            required = min(len(message.content), MAX_MESSAGE_LENGTH)
            wait_time = self._estimate_wait_time(message.guild.id, required)
            suffix = f"（約{wait_time}秒後に回復します）" if wait_time > 0 else ""
            await message.reply(f"読み上げ制限に達しました{suffix}")
            return

        text = self._prepare_message_text(message)
        speaker_id = self._speaker_id_for(message)
        try:
            session.queue.put_nowait(SpeechItem(text=text, speaker_id=speaker_id))
        except asyncio.QueueFull:
            await message.reply("読み上げ待ちが多すぎるため、この投稿はスキップしました")
            return
        self._ensure_worker(message.guild, session)

    async def on_voice_state_update(
        self,
        member: discord.Member,
        _before: discord.VoiceState,
        _after: discord.VoiceState,
    ) -> None:
        await self._disconnect_if_empty(member.guild)

    def _register_commands(self) -> None:
        @self.tree.command(name="join", description="ボイスチャンネルに接続します")
        async def join(interaction: discord.Interaction) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                await interaction.response.send_message(
                    "このコマンドはサーバー内でのみ使用できます",
                )
                return

            voice = interaction.user.voice
            if voice is None or voice.channel is None:
                await interaction.response.send_message(
                    "ユーザーがボイスチャンネルに参加していません。",
                )
                return
            if interaction.channel_id is None:
                await interaction.response.send_message(
                    "テキストチャンネル情報が取得できませんでした。",
                )
                return

            reply = await self._join_member_voice(
                interaction.guild,
                interaction.user,
                interaction.channel_id,
            )
            await interaction.response.send_message(reply)

        @self.tree.command(name="leave", description="ボイスチャンネルから切断します")
        async def leave(interaction: discord.Interaction) -> None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "このコマンドはサーバー内でのみ使用できます",
                )
                return

            voice_client = interaction.guild.voice_client
            if not isinstance(voice_client, discord.VoiceClient):
                await interaction.response.send_message("ボイスチャンネルに接続していません")
                return

            await self._disconnect_guild(interaction.guild, voice_client)
            await interaction.response.send_message("ボイスチャンネルから切断しました")

        @self.tree.command(name="skip", description="現在の読み上げをスキップします")
        async def skip(interaction: discord.Interaction) -> None:
            if interaction.guild is None or not self._skip_guild(interaction.guild):
                await interaction.response.send_message("ボイスチャンネルに接続していません")
                return

            await interaction.response.send_message("現在の読み上げをスキップしました")

        @self.tree.command(name="s", description="現在の読み上げをスキップします")
        async def s(interaction: discord.Interaction) -> None:
            if interaction.guild is None or not self._skip_guild(interaction.guild):
                await interaction.response.send_message("ボイスチャンネルに接続していません")
                return

            await interaction.response.send_message("現在の読み上げをスキップしました")

        dict_group = app_commands.Group(name="dict", description="サーバー辞書の管理")

        @dict_group.command(name="add", description="単語を辞書に追加")
        @app_commands.describe(word="単語", reading="読み方", regex="正規表現として扱うか")
        async def dict_add(
            interaction: discord.Interaction,
            word: str,
            reading: str,
            regex: bool = False,
        ) -> None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "このコマンドはサーバー内でのみ使用できます",
                )
                return

            entries = self.database.get_server_dict(interaction.guild.id, self.settings.bot_id)
            if len(entries) >= MAX_DICT_ENTRIES:
                await interaction.response.send_message(
                    "サーバー辞書には最大27個の単語を登録できます",
                )
                return
            error_message = self._validate_dict_entry(word, reading, regex)
            if error_message is not None:
                await interaction.response.send_message(error_message)
                return

            self.database.insert_server_dict_entry(
                interaction.guild.id,
                self.settings.bot_id,
                word,
                reading,
                regex,
            )
            await interaction.response.send_message(
                f"単語を辞書に追加しました\n単語: `{word}`\n読み: `{reading}`\n正規表現: `{regex}`",
            )

        @dict_group.command(name="remove", description="単語を辞書から削除")
        @app_commands.describe(word="単語")
        async def dict_remove(interaction: discord.Interaction, word: str) -> None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "このコマンドはサーバー内でのみ使用できます",
                )
                return

            self.database.delete_server_dict_entry(
                interaction.guild.id,
                self.settings.bot_id,
                word,
            )
            await interaction.response.send_message(
                f"単語を辞書から削除しました\n削除した単語: `{word}`",
            )

        @dict_group.command(name="list", description="辞書の内容を表示")
        async def dict_list(interaction: discord.Interaction) -> None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "このコマンドはサーバー内でのみ使用できます",
                )
                return

            entries = self.database.get_server_dict(interaction.guild.id, self.settings.bot_id)
            if not entries:
                await interaction.response.send_message("辞書に登録されている単語がありません")
                return

            lines = [
                f"{index}. `{word}` -> `{reading}` (regex: `{regex}`)"
                for index, (word, reading, regex) in enumerate(entries, start=1)
            ]
            await interaction.response.send_message("\n".join(lines[:MAX_DICT_ENTRIES]))

        self.tree.add_command(dict_group)

        settings_group = app_commands.Group(name="settings", description="読み上げ設定")

        @settings_group.command(name="show", description="現在の読み上げ設定を表示")
        async def settings_show(interaction: discord.Interaction) -> None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "このコマンドはサーバー内でのみ使用できます",
                )
                return

            guild_settings = self.database.get_guild_settings(
                interaction.guild.id,
                self.settings.bot_id,
                self.settings.speaker_id,
            )
            mode = (
                "名前/チャンネル名"
                if guild_settings.mention_read_mode == "name"
                else "リンク省略"
            )
            read_name = "有効" if guild_settings.read_author_name else "無効"
            await interaction.response.send_message(
                "\n".join(
                    [
                        f"メンション/Discord URL: `{mode}`",
                        f"名前読み上げ: `{read_name}`",
                        f"デフォルト話者ID: `{guild_settings.default_speaker_id}`",
                    ],
                ),
            )

        @settings_group.command(
            name="mention",
            description="メンションやDiscordチャンネルURLの読み方を変更",
        )
        @app_commands.choices(
            mode=[
                app_commands.Choice(name="名前/チャンネル名", value="name"),
                app_commands.Choice(name="リンク省略", value="omit"),
            ],
        )
        async def settings_mention(
            interaction: discord.Interaction,
            mode: app_commands.Choice[str],
        ) -> None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "このコマンドはサーバー内でのみ使用できます",
                )
                return

            self.database.set_mention_read_mode(
                interaction.guild.id,
                self.settings.bot_id,
                mode.value,
            )
            await interaction.response.send_message(f"読み方を `{mode.name}` に変更しました")

        @settings_group.command(name="read_name", description="読み上げ前に投稿者名を読むか変更")
        async def settings_read_name(interaction: discord.Interaction, enabled: bool) -> None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "このコマンドはサーバー内でのみ使用できます",
                )
                return

            self.database.set_read_author_name(
                interaction.guild.id,
                self.settings.bot_id,
                enabled,
            )
            state = "有効" if enabled else "無効"
            await interaction.response.send_message(f"名前読み上げを `{state}` にしました")

        @settings_group.command(name="default_speaker", description="デフォルト話者IDを変更")
        async def settings_default_speaker(
            interaction: discord.Interaction,
            speaker_id: app_commands.Range[int, 0, 100],
        ) -> None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "このコマンドはサーバー内でのみ使用できます",
                )
                return

            self.database.set_default_speaker_id(
                interaction.guild.id,
                self.settings.bot_id,
                speaker_id,
            )
            await interaction.response.send_message(f"デフォルト話者IDを `{speaker_id}` にしました")

        @settings_group.command(name="user_speaker", description="ユーザーごとの話者IDを設定")
        async def settings_user_speaker(
            interaction: discord.Interaction,
            user: discord.Member,
            speaker_id: app_commands.Range[int, 0, 100],
        ) -> None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "このコマンドはサーバー内でのみ使用できます",
                )
                return

            self.database.set_user_speaker_id(
                interaction.guild.id,
                self.settings.bot_id,
                user.id,
                speaker_id,
            )
            await interaction.response.send_message(
                f"{user.display_name} の話者IDを `{speaker_id}` にしました",
            )

        @settings_group.command(name="clear_user_speaker", description="ユーザーごとの話者IDを解除")
        async def settings_clear_user_speaker(
            interaction: discord.Interaction,
            user: discord.Member,
        ) -> None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "このコマンドはサーバー内でのみ使用できます",
                )
                return

            self.database.delete_user_speaker_id(
                interaction.guild.id,
                self.settings.bot_id,
                user.id,
            )
            await interaction.response.send_message(f"{user.display_name} の話者設定を解除しました")

        self.tree.add_command(settings_group)

    async def close(self) -> None:
        for guild_id in tuple(self.sessions):
            self._drop_session(guild_id)
        self.database.close()
        await super().close()

    def _is_bot_mentioned(self, message: discord.Message) -> bool:
        return self.user is not None and self.user in message.mentions

    async def _join_from_message(self, message: discord.Message) -> None:
        if message.guild is None or not isinstance(message.author, discord.Member):
            return

        reply = await self._join_member_voice(
            message.guild,
            message.author,
            message.channel.id,
        )
        await message.reply(reply)

    async def _join_member_voice(
        self,
        guild: discord.Guild,
        member: discord.Member,
        text_channel_id: int,
    ) -> str:
        voice = member.voice
        if voice is None or voice.channel is None:
            return "ボイスチャンネルに参加してから呼んでください。"

        voice_client = guild.voice_client
        if isinstance(voice_client, discord.VoiceClient):
            await voice_client.move_to(voice.channel)
            action = "移動しました"
        else:
            voice_client = cast(discord.VoiceClient, await voice.channel.connect())
            action = "接続しました"

        self.sessions[guild.id] = GuildSession(
            voice_channel_id=voice.channel.id,
            text_channel_id=text_channel_id,
            tokens=self.settings.max_tokens,
        )
        LOGGER.info("Joined guild=%s channel=%s", guild.id, voice_client.channel)
        return f"{voice.channel.mention} に{action}"

    async def _disconnect_if_empty(self, guild: discord.Guild) -> None:
        voice_client = guild.voice_client
        if not isinstance(voice_client, discord.VoiceClient):
            return

        channel_id = getattr(voice_client.channel, "id", None)
        if channel_id is None:
            return

        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.VoiceChannel | discord.StageChannel):
            return

        non_bot_members = [voice_member for voice_member in channel.members if not voice_member.bot]
        if non_bot_members:
            return

        await self._disconnect_guild(guild, voice_client)
        LOGGER.info("Disconnected from guild=%s because the voice channel is empty", guild.id)

    async def _disconnect_guild(
        self,
        guild: discord.Guild,
        voice_client: discord.VoiceClient,
    ) -> None:
        self._drop_session(guild.id)
        await voice_client.disconnect(force=False)

    def _drop_session(self, guild_id: int) -> None:
        session = self.sessions.pop(guild_id, None)
        if session is None:
            return

        while not session.queue.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                session.queue.get_nowait()
                session.queue.task_done()

        worker = session.worker
        if worker is not None and not worker.done() and worker is not asyncio.current_task():
            worker.cancel()

    def _skip_guild(self, guild: discord.Guild) -> bool:
        voice_client = guild.voice_client
        if not isinstance(voice_client, discord.VoiceClient):
            return False
        voice_client.stop()
        return True

    def _speaker_id_for(self, message: discord.Message) -> int:
        if message.guild is None:
            return self.settings.speaker_id
        guild_settings = self.database.get_guild_settings(
            message.guild.id,
            self.settings.bot_id,
            self.settings.speaker_id,
        )
        user_speaker_id = self.database.get_user_speaker_id(
            message.guild.id,
            self.settings.bot_id,
            message.author.id,
        )
        return user_speaker_id if user_speaker_id is not None else guild_settings.default_speaker_id

    def _prepare_message_text(self, message: discord.Message) -> str:
        if message.guild is None:
            return message.content

        guild_settings = self.database.get_guild_settings(
            message.guild.id,
            self.settings.bot_id,
            self.settings.speaker_id,
        )
        content = self._replace_discord_references(
            message.guild,
            message.content,
            guild_settings.mention_read_mode,
        )
        if message.attachments:
            content = f"添付ファイル {content}"
        if guild_settings.read_author_name:
            content = f"{message.author.display_name}、{content}"
        return content

    def _replace_discord_references(
        self,
        guild: discord.Guild,
        content: str,
        mention_read_mode: str,
    ) -> str:
        replacement = "りんくしょうりゃく"
        if mention_read_mode == "omit":
            content = MENTION_PATTERN.sub(replacement, content)
            return DISCORD_CHANNEL_URL_PATTERN.sub(replacement, content)

        content = MENTION_PATTERN.sub(lambda match: self._mention_name(guild, match), content)
        return DISCORD_CHANNEL_URL_PATTERN.sub(
            lambda match: self._channel_url_name(guild, match),
            content,
        )

    def _mention_name(self, guild: discord.Guild, match: re.Match[str]) -> str:
        kind = match.group(1)
        discord_id = int(match.group(2))
        if kind in {"@!", "@"}:
            member = guild.get_member(discord_id)
            return member.display_name if member is not None else "メンション"
        if kind == "@&":
            role = guild.get_role(discord_id)
            return role.name if role is not None else "ロール"

        channel = guild.get_channel_or_thread(discord_id)
        return channel.name if channel is not None else "チャンネル"

    def _channel_url_name(self, guild: discord.Guild, match: re.Match[str]) -> str:
        channel_id = int(match.group(2))
        channel = guild.get_channel_or_thread(channel_id)
        return channel.name if channel is not None else "チャンネル"

    def _validate_dict_entry(self, word: str, reading: str, regex: bool) -> str | None:
        error_message = None
        if not word.strip() or not reading.strip():
            error_message = "単語と読みは空にできません"
        elif len(word) > MAX_DICT_WORD_LENGTH:
            error_message = f"単語は{MAX_DICT_WORD_LENGTH}文字以内にしてください"
        elif len(reading) > MAX_DICT_READING_LENGTH:
            error_message = f"読みは{MAX_DICT_READING_LENGTH}文字以内にしてください"
        elif regex:
            try:
                re.compile(word)
            except re.error as exc:
                error_message = f"正規表現として解釈できません: {exc}"
            else:
                if NESTED_QUANTIFIER_PATTERN.search(word):
                    error_message = "処理が極端に重くなる可能性がある正規表現は登録できません"
        return error_message

    def _consume_token(self, guild_id: int, message: str) -> bool:
        session = self.sessions.get(guild_id)
        if session is None:
            return False

        now = datetime.now(UTC)
        elapsed = (now - session.last_token_refill).total_seconds()
        if elapsed >= REFILL_INTERVAL_SECONDS:
            periods = int(elapsed // REFILL_INTERVAL_SECONDS)
            session.tokens = min(
                self.settings.max_tokens,
                session.tokens + periods * REFILL_RATE,
            )
            session.last_token_refill = now

        tokens_needed = min(len(message), MAX_MESSAGE_LENGTH)
        if session.tokens < tokens_needed:
            return False

        session.tokens -= tokens_needed
        return True

    def _estimate_wait_time(self, guild_id: int, required_tokens: int) -> int:
        session = self.sessions.get(guild_id)
        if session is None or session.tokens >= required_tokens:
            return 0
        shortage = required_tokens - session.tokens
        periods = (shortage + REFILL_RATE - 1) // REFILL_RATE
        return periods * REFILL_INTERVAL_SECONDS

    def _ensure_worker(self, guild: discord.Guild, session: GuildSession) -> None:
        if session.worker is None or session.worker.done():
            session.worker = asyncio.create_task(self._speak_worker(guild, session))

    async def _speak_worker(self, guild: discord.Guild, session: GuildSession) -> None:
        while True:
            item = await session.queue.get()
            voice_client = guild.voice_client
            if not isinstance(voice_client, discord.VoiceClient):
                session.queue.task_done()
                return

            try:
                converted = self.translator.convert(item.text, guild.id, self.settings.bot_id)
                wav_data = await asyncio.to_thread(
                    self.synthesizer.generate,
                    converted,
                    item.speaker_id,
                )
                await self._play_wav_data(voice_client, wav_data)
            except Exception:
                LOGGER.exception("Failed to play TTS for guild=%s", guild.id)
            finally:
                session.queue.task_done()

    async def _play_wav_data(
        self,
        voice_client: discord.VoiceClient,
        wav_data: bytes,
    ) -> None:
        finished = asyncio.Event()

        def on_finished(error: Exception | None) -> None:
            if error is not None:
                LOGGER.warning("Discord playback failed: %s", error)
            self.loop.call_soon_threadsafe(finished.set)

        source = discord.FFmpegPCMAudio(
            source=BytesIO(wav_data),
            executable=self.settings.ffmpeg_path,
            pipe=True,
        )
        try:
            voice_client.play(source, after=on_finished)
            await finished.wait()
        except Exception:
            source.cleanup()
            raise


def make_bot(settings: Settings) -> YomiageBot:
    database = Database(settings.database_path)
    translator = Translator(database)
    synthesizer = VoicevoxSynthesizer(settings)
    return YomiageBot(settings, database, translator, synthesizer)
