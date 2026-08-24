from __future__ import annotations

import logging
import re
from typing import cast

import discord
from discord import app_commands

from yomiage.commands import setup_commands
from yomiage.config import Settings
from yomiage.database import Database
from yomiage.speech import GuildSession, SessionManager, SpeechItem
from yomiage.translator import Translator
from yomiage.voicevox import SynthesizerLike, VoicevoxSynthesizer

LOGGER = logging.getLogger(__name__)
MAX_MESSAGE_LENGTH = 80
SKIP_SHORTCUTS = frozenset({"s", "S", "!s", "!S", "！s", "！S"})
CUSTOM_EMOJI_PATTERN = re.compile(r"<a?:([A-Za-z0-9_]{2,32}):\d+>")
MENTION_PATTERN = re.compile(r"<(@!?|@&|#)(\d+)>")
DISCORD_CHANNEL_URL_PATTERN = re.compile(
    r"https?://(?:canary\.|ptb\.)?discord(?:app)?\.com/channels/(\d+|@me)/(\d+)(?:/\d+)?",
)
SERVER_CHAT_PREFIX_PATTERN = re.compile(r"^\[[^\]]+\]<[^>]+>\s*")


class YomiageBot(discord.Client):
    def __init__(
        self,
        settings: Settings,
        database: Database,
        translator: Translator,
        synthesizer: SynthesizerLike,
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
        self.session_manager = SessionManager(settings, database, translator, synthesizer)
        self.tree.on_error = self._on_app_command_error
        setup_commands(self)

    async def setup_hook(self) -> None:
        LOGGER.info("Syncing Discord slash commands")
        commands = await self.tree.sync()
        LOGGER.info("Synced %s Discord slash command(s)", len(commands))

    async def on_ready(self) -> None:
        user = self.user
        if user is not None:
            LOGGER.info("Bot ready: %s (%s)", user, user.id)

    async def on_disconnect(self) -> None:
        LOGGER.warning("Discord client disconnected")

    async def on_resumed(self) -> None:
        LOGGER.info("Discord client resumed")

    async def on_guild_join(self, guild: discord.Guild) -> None:
        LOGGER.info("Joined guild=%s", guild.id)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        LOGGER.info("Removed from guild=%s", guild.id)
        await self.session_manager.close(guild.id)

    async def on_message(self, message: discord.Message) -> None:
        if self._is_own_message(message) or not message.guild:
            return
        if not message.content and not message.attachments:
            return

        if self._is_bot_mentioned(message):
            await self._join_from_message(message)
            return

        session = self.session_manager.get(message.guild.id)
        if session is None or message.channel.id != session.text_channel_id:
            return

        await self._handle_session_message(message, message.guild, session)

    async def _handle_session_message(
        self,
        message: discord.Message,
        guild: discord.Guild,
        session: GuildSession,
    ) -> None:
        if message.content.strip() in SKIP_SHORTCUTS:
            self._skip_guild(guild)
            return

        tokens_needed = min(len(message.content), MAX_MESSAGE_LENGTH)
        if not session.token_bucket.try_consume(tokens_needed):
            wait_time = session.token_bucket.wait_time_seconds(tokens_needed)
            suffix = f"（約{int(wait_time)}秒後に回復します）" if wait_time > 0 else ""
            await message.reply(f"読み上げ制限に達しました{suffix}")
            return

        text = self._prepare_message_text(message)
        speaker_id = self._speaker_id_for(message)
        if not self.session_manager.enqueue(session, SpeechItem(text=text, speaker_id=speaker_id)):
            await message.reply("読み上げ待ちが多すぎるため、この投稿はスキップしました")
            return
        self.session_manager.ensure_worker(guild, session)

    async def on_voice_state_update(
        self,
        member: discord.Member,
        _before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if self.user is not None and member.id == self.user.id:
            await self._handle_own_voice_state_update(member.guild, after)
            return

        await self._disconnect_if_empty(member.guild)

    async def _on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "このコマンドを実行するには「サーバーの管理」権限が必要です"
        elif isinstance(error, app_commands.NoPrivateMessage):
            message = "このコマンドはサーバー内でのみ使用できます"
        else:
            LOGGER.error("Unhandled app command error", exc_info=error)
            message = "コマンドの実行中にエラーが発生しました"

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def close(self) -> None:
        await self.session_manager.close_all()
        self.database.close()
        await super().close()

    def _is_bot_mentioned(self, message: discord.Message) -> bool:
        return self.user is not None and self.user in message.mentions

    def _is_own_message(self, message: discord.Message) -> bool:
        return self.user is not None and message.author.id == self.user.id

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
            await guild.change_voice_state(channel=voice.channel, self_deaf=True)
            action = "移動しました"
        else:
            voice_client = cast(discord.VoiceClient, await voice.channel.connect(self_deaf=True))
            action = "接続しました"

        await self.session_manager.open(guild.id, voice.channel.id, text_channel_id)
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
        await self.session_manager.close(guild.id)
        await voice_client.disconnect(force=False)

    async def _handle_own_voice_state_update(
        self,
        guild: discord.Guild,
        after: discord.VoiceState,
    ) -> None:
        session = self.session_manager.get(guild.id)
        if session is None:
            return

        if after.channel is None:
            await self.session_manager.close(guild.id)
            LOGGER.info("Voice session closed after bot disconnected from guild=%s", guild.id)
            return

        session.voice_channel_id = after.channel.id

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
        content = message.content
        if guild_settings.server_chat_enabled:
            content = SERVER_CHAT_PREFIX_PATTERN.sub("", content, count=1)
        content = CUSTOM_EMOJI_PATTERN.sub(lambda match: match.group(1), content)
        content = self._replace_discord_references(
            message.guild,
            content,
            guild_settings.mention_read_mode,
        )
        if message.attachments:
            content = f"添付ファイル {content}".strip()
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


def make_bot(settings: Settings) -> YomiageBot:
    database = Database(settings.database_path)
    translator = Translator(database)
    synthesizer = VoicevoxSynthesizer(settings)
    return YomiageBot(settings, database, translator, synthesizer)
