"""Slash command definitions: join/leave/skip, server dictionary, and settings."""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from yomiage.voice_catalog import (
    format_voice_license,
    format_voice_styles,
    voice_catalog_pages,
    voice_license_pages,
)

MAX_DICT_ENTRIES = 27
MAX_DICT_WORD_LENGTH = 120
MAX_DICT_READING_LENGTH = 80
DISCORD_MESSAGE_LIMIT = 2000
SPEAKER_ID_INPUT_RANGE = app_commands.Range[int, 0, 10_000]
NESTED_QUANTIFIER_PATTERN = re.compile(r"\((?:[^()\\]|\\.)*[*+](?:[^()\\]|\\.)*\)[*+{]")
GUILD_ONLY_MESSAGE = "このコマンドはサーバー内でのみ使用できます"
NOT_CONNECTED_MESSAGE = "ボイスチャンネルに接続していません"
# Look-alike for "`" so user text cannot close an inline code span early.
BACKTICK_SUBSTITUTE = "ˋ"

LOGGER = logging.getLogger(__name__)
VOICE_PAGINATOR_TIMEOUT_SECONDS = 60.0

if TYPE_CHECKING:
    from yomiage.bot import YomiageBot


def _validate_dict_entry(word: str, reading: str, regex: bool) -> str | None:
    if not word.strip() or not reading.strip():
        return "単語と読みは空にできません"
    if len(word) > MAX_DICT_WORD_LENGTH:
        return f"単語は{MAX_DICT_WORD_LENGTH}文字以内にしてください"
    if len(reading) > MAX_DICT_READING_LENGTH:
        return f"読みは{MAX_DICT_READING_LENGTH}文字以内にしてください"
    if regex:
        try:
            re.compile(word)
        except re.error as exc:
            return f"正規表現として解釈できません: {exc}"
        if NESTED_QUANTIFIER_PATTERN.search(word):
            return "処理が極端に重くなる可能性がある正規表現は登録できません"
    return None


def _inline_code(text: str) -> str:
    """Render user-supplied text as inline code without letting it break out of the span."""
    return f"`{text.replace('`', BACKTICK_SUBSTITUTE)}`"


def _chunk_lines(lines: Sequence[str], limit: int = DISCORD_MESSAGE_LIMIT) -> list[str]:
    """Join lines into messages that each fit within Discord's length limit."""
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = line[:limit]
    if current:
        chunks.append(current)
    return chunks


def _speaker_unavailable_message(speaker_id: int) -> str:
    return f"話者ID `{speaker_id}` は現在ロードされているVOICEVOXモデルにありません"


class _EmbedPaginator(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, embeds: Sequence[discord.Embed]) -> None:
        super().__init__(timeout=VOICE_PAGINATOR_TIMEOUT_SECONDS)
        self._interaction = interaction
        self._embeds = embeds
        self._page_index = 0
        self._sync_buttons()

    @property
    def current_embed(self) -> discord.Embed:
        return self._embeds[self._page_index]

    async def on_timeout(self) -> None:
        with contextlib.suppress(discord.HTTPException, discord.NotFound):
            await self._interaction.edit_original_response(view=None)

    @discord.ui.button(label="前へ", style=discord.ButtonStyle.secondary)
    async def previous_page(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[_EmbedPaginator],
    ) -> None:
        if self._page_index > 0:
            self._page_index -= 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.current_embed, view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.secondary, disabled=True)
    async def page_label(
        self,
        _interaction: discord.Interaction,
        _button: discord.ui.Button[_EmbedPaginator],
    ) -> None:
        return

    @discord.ui.button(label="次へ", style=discord.ButtonStyle.secondary)
    async def next_page(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[_EmbedPaginator],
    ) -> None:
        if self._page_index < len(self._embeds) - 1:
            self._page_index += 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.current_embed, view=self)

    def _sync_buttons(self) -> None:
        self.previous_page.disabled = self._page_index == 0
        self.next_page.disabled = self._page_index >= len(self._embeds) - 1
        self.page_label.label = f"{self._page_index + 1}/{len(self._embeds)}"


def _build_paged_embeds[EntryT](
    title: str,
    pages: Sequence[Sequence[EntryT]],
    field_name: Callable[[EntryT], str],
    field_value: Callable[[EntryT], str],
    description: str | None = None,
) -> list[discord.Embed]:
    embeds: list[discord.Embed] = []
    for page_index, entries in enumerate(pages, start=1):
        embed = discord.Embed(
            title=f"{title} ({page_index}/{len(pages)})",
            description=description,
            color=discord.Color.blurple(),
        )
        for entry in entries:
            embed.add_field(name=field_name(entry), value=field_value(entry), inline=False)
        embeds.append(embed)
    return embeds


def _build_voice_catalog_embeds() -> list[discord.Embed]:
    return _build_paged_embeds(
        "VOICEVOX 話者ID一覧",
        voice_catalog_pages(),
        lambda entry: entry.character,
        format_voice_styles,
    )


def _build_voice_license_embeds() -> list[discord.Embed]:
    return _build_paged_embeds(
        "VOICEVOX クレジット表記",
        voice_license_pages(),
        lambda entry: entry.character,
        format_voice_license,
        description="詳細な条件は各キャラクターの利用規約を確認してください。",
    )


def setup_commands(bot: YomiageBot) -> None:
    tree = bot.tree

    @tree.command(name="join", description="ボイスチャンネルに接続します")
    @app_commands.guild_only()
    async def join(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None  # noqa: S101 - guaranteed by guild_only()
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(GUILD_ONLY_MESSAGE)
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

        # Connecting can exceed Discord's 3 second interaction response deadline.
        await interaction.response.defer(thinking=True)
        reply = await bot._join_member_voice(  # noqa: SLF001 - commands module is bot's collaborator
            interaction.guild,
            interaction.user,
            interaction.channel_id,
        )
        await interaction.followup.send(reply)

    @tree.command(name="leave", description="ボイスチャンネルから切断します")
    @app_commands.guild_only()
    async def leave(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None  # noqa: S101
        voice_client = interaction.guild.voice_client
        if not isinstance(voice_client, discord.VoiceClient):
            await interaction.response.send_message(NOT_CONNECTED_MESSAGE)
            return

        # Session teardown may wait for an in-flight synthesis thread to stop.
        await interaction.response.defer(thinking=True)
        await bot._disconnect_guild(interaction.guild, voice_client)  # noqa: SLF001
        await interaction.followup.send("ボイスチャンネルから切断しました")

    async def skip_current(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None  # noqa: S101
        if not bot._skip_guild(interaction.guild):  # noqa: SLF001
            await interaction.response.send_message(NOT_CONNECTED_MESSAGE)
            return
        await interaction.response.send_message("現在の読み上げをスキップしました")

    @tree.command(name="skip", description="現在の読み上げをスキップします")
    @app_commands.guild_only()
    async def skip(interaction: discord.Interaction) -> None:
        await skip_current(interaction)

    @tree.command(name="s", description="現在の読み上げをスキップします")
    @app_commands.guild_only()
    async def s(interaction: discord.Interaction) -> None:
        await skip_current(interaction)

    dict_group = app_commands.Group(name="dict", description="サーバー辞書の管理")

    @dict_group.command(name="add", description="単語を辞書に追加")
    @app_commands.describe(word="単語", reading="読み方", regex="正規表現として扱うか")
    @app_commands.guild_only()
    async def dict_add(
        interaction: discord.Interaction,
        word: str,
        reading: str,
        regex: bool = False,
    ) -> None:
        assert interaction.guild is not None  # noqa: S101
        entries = bot.database.get_server_dict(interaction.guild.id, bot.settings.bot_id)
        is_new_word = word not in {existing_word for existing_word, _, _ in entries}
        if is_new_word and len(entries) >= MAX_DICT_ENTRIES:
            await interaction.response.send_message(
                f"サーバー辞書には最大{MAX_DICT_ENTRIES}個の単語を登録できます",
            )
            return

        error_message = _validate_dict_entry(word, reading, regex)
        if error_message is not None:
            await interaction.response.send_message(error_message)
            return

        bot.database.insert_server_dict_entry(
            interaction.guild.id,
            bot.settings.bot_id,
            word,
            reading,
            regex,
        )
        await interaction.response.send_message(
            "単語を辞書に追加しました\n"
            f"単語: {_inline_code(word)}\n"
            f"読み: {_inline_code(reading)}\n"
            f"正規表現: `{regex}`",
        )

    @dict_group.command(name="remove", description="単語を辞書から削除")
    @app_commands.describe(word="単語")
    @app_commands.guild_only()
    async def dict_remove(interaction: discord.Interaction, word: str) -> None:
        assert interaction.guild is not None  # noqa: S101
        deleted = bot.database.delete_server_dict_entry(
            interaction.guild.id,
            bot.settings.bot_id,
            word,
        )
        if deleted:
            await interaction.response.send_message(
                f"単語を辞書から削除しました\n削除した単語: {_inline_code(word)}",
            )
        else:
            await interaction.response.send_message("その単語は登録されていません")

    @dict_group.command(name="list", description="辞書の内容を表示")
    @app_commands.guild_only()
    async def dict_list(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None  # noqa: S101
        entries = bot.database.get_server_dict(interaction.guild.id, bot.settings.bot_id)
        if not entries:
            await interaction.response.send_message("辞書に登録されている単語がありません")
            return

        lines = [
            f"{index}. {_inline_code(word)} -> {_inline_code(reading)} (regex: `{regex}`)"
            for index, (word, reading, regex) in enumerate(entries[:MAX_DICT_ENTRIES], start=1)
        ]
        # A full dictionary can exceed one message, so send the rest as follow-ups.
        first, *rest = _chunk_lines(lines)
        await interaction.response.send_message(first)
        for chunk in rest:
            await interaction.followup.send(chunk)

    tree.add_command(dict_group)

    voice_group = app_commands.Group(name="voice", description="VOICEVOX話者ID")

    @voice_group.command(name="list", description="VOICEVOXのキャラクターと話者IDを表示")
    @app_commands.guild_only()
    async def voice_list(interaction: discord.Interaction) -> None:
        embeds = _build_voice_catalog_embeds()
        view = _EmbedPaginator(interaction, embeds)
        await interaction.response.send_message(embed=view.current_embed, view=view)

    @voice_group.command(name="license", description="VOICEVOXキャラクターのクレジット表記を表示")
    @app_commands.guild_only()
    async def voice_license(interaction: discord.Interaction) -> None:
        embeds = _build_voice_license_embeds()
        view = _EmbedPaginator(interaction, embeds)
        await interaction.response.send_message(embed=view.current_embed, view=view)

    tree.add_command(voice_group)

    settings_group = app_commands.Group(name="settings", description="読み上げ設定")

    @settings_group.command(name="show", description="現在の読み上げ設定を表示")
    @app_commands.guild_only()
    async def settings_show(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None  # noqa: S101
        guild_settings = bot.database.get_guild_settings(
            interaction.guild.id,
            bot.settings.bot_id,
            bot.settings.speaker_id,
        )
        mode = "名前/チャンネル名" if guild_settings.mention_read_mode == "name" else "リンク省略"
        read_name = "有効" if guild_settings.read_author_name else "無効"
        server_chat = "有効" if guild_settings.server_chat_enabled else "無効"
        await interaction.response.send_message(
            "\n".join(
                [
                    f"メンション/Discord URL: `{mode}`",
                    f"名前読み上げ: `{read_name}`",
                    f"ServerChat整形: `{server_chat}`",
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
    @app_commands.guild_only()
    async def settings_mention(
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
    ) -> None:
        assert interaction.guild is not None  # noqa: S101
        bot.database.set_mention_read_mode(
            interaction.guild.id,
            bot.settings.bot_id,
            mode.value,
            bot.settings.speaker_id,
        )
        await interaction.response.send_message(f"読み方を `{mode.name}` に変更しました")

    @settings_group.command(
        name="read_name",
        description="読み上げ前に投稿者名を読むか変更",
    )
    @app_commands.guild_only()
    async def settings_read_name(interaction: discord.Interaction, enabled: bool) -> None:
        assert interaction.guild is not None  # noqa: S101
        bot.database.set_read_author_name(
            interaction.guild.id,
            bot.settings.bot_id,
            enabled,
            bot.settings.speaker_id,
        )
        state = "有効" if enabled else "無効"
        await interaction.response.send_message(f"名前読み上げを `{state}` にしました")

    @settings_group.command(
        name="serverchat",
        description="ServerChat形式の接頭辞を省略するか変更",
    )
    @app_commands.guild_only()
    async def settings_serverchat(interaction: discord.Interaction, enabled: bool) -> None:
        assert interaction.guild is not None  # noqa: S101
        bot.database.set_server_chat_enabled(
            interaction.guild.id,
            bot.settings.bot_id,
            enabled,
            bot.settings.speaker_id,
        )
        state = "有効" if enabled else "無効"
        await interaction.response.send_message(f"ServerChat整形を `{state}` にしました")

    @settings_group.command(
        name="default_speaker",
        description="デフォルト話者IDを変更",
    )
    @app_commands.guild_only()
    async def settings_default_speaker(
        interaction: discord.Interaction,
        speaker_id: SPEAKER_ID_INPUT_RANGE,
    ) -> None:
        assert interaction.guild is not None  # noqa: S101
        if not bot.synthesizer.is_style_available(speaker_id):
            await interaction.response.send_message(_speaker_unavailable_message(speaker_id))
            return

        bot.database.set_default_speaker_id(interaction.guild.id, bot.settings.bot_id, speaker_id)
        await interaction.response.send_message(f"デフォルト話者IDを `{speaker_id}` にしました")

    @settings_group.command(
        name="user_speaker",
        description="自分の話者IDを設定",
    )
    @app_commands.guild_only()
    async def settings_user_speaker(
        interaction: discord.Interaction,
        speaker_id: SPEAKER_ID_INPUT_RANGE,
    ) -> None:
        assert interaction.guild is not None  # noqa: S101
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(GUILD_ONLY_MESSAGE)
            return

        if not bot.synthesizer.is_style_available(speaker_id):
            await interaction.response.send_message(_speaker_unavailable_message(speaker_id))
            return

        bot.database.set_user_speaker_id(
            interaction.guild.id,
            bot.settings.bot_id,
            interaction.user.id,
            speaker_id,
        )
        await interaction.response.send_message(
            f"あなたの話者IDを `{speaker_id}` にしました",
        )

    @settings_group.command(
        name="clear_user_speaker",
        description="自分の話者ID設定を解除",
    )
    @app_commands.guild_only()
    async def settings_clear_user_speaker(
        interaction: discord.Interaction,
    ) -> None:
        assert interaction.guild is not None  # noqa: S101
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(GUILD_ONLY_MESSAGE)
            return

        bot.database.delete_user_speaker_id(
            interaction.guild.id,
            bot.settings.bot_id,
            interaction.user.id,
        )
        await interaction.response.send_message("あなたの話者設定を解除しました")

    tree.add_command(settings_group)
