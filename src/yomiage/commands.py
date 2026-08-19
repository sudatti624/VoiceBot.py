"""Slash command definitions: join/leave/skip, server dictionary, and settings.

Server-wide settings and the dictionary are gated behind Discord's "Manage
Guild" permission through a couple of small shared helpers, so the same check
is not copy-pasted into every command body.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import discord
from discord import app_commands

MAX_DICT_ENTRIES = 27
MAX_DICT_WORD_LENGTH = 120
MAX_DICT_READING_LENGTH = 80
SPEAKER_ID_INPUT_RANGE = app_commands.Range[int, 0, 10_000]
NESTED_QUANTIFIER_PATTERN = re.compile(r"\((?:[^()\\]|\\.)*[*+](?:[^()\\]|\\.)*\)[*+{]")

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from yomiage.bot import YomiageBot

require_manage_guild = app_commands.checks.has_permissions(manage_guild=True)


def _has_manage_guild(member: discord.Member) -> bool:
    return member.guild_permissions.manage_guild


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


def setup_commands(bot: YomiageBot) -> None:
    tree = bot.tree

    @tree.command(name="join", description="ボイスチャンネルに接続します")
    @app_commands.guild_only()
    async def join(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None  # noqa: S101 - guaranteed by guild_only()
        if not isinstance(interaction.user, discord.Member):
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

        reply = await bot._join_member_voice(  # noqa: SLF001 - commands module is bot's collaborator
            interaction.guild,
            interaction.user,
            interaction.channel_id,
        )
        await interaction.response.send_message(reply)

    @tree.command(name="leave", description="ボイスチャンネルから切断します")
    @app_commands.guild_only()
    async def leave(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None  # noqa: S101
        voice_client = interaction.guild.voice_client
        if not isinstance(voice_client, discord.VoiceClient):
            await interaction.response.send_message("ボイスチャンネルに接続していません")
            return

        await bot._disconnect_guild(interaction.guild, voice_client)  # noqa: SLF001
        await interaction.response.send_message("ボイスチャンネルから切断しました")

    @tree.command(name="skip", description="現在の読み上げをスキップします")
    @app_commands.guild_only()
    async def skip(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None  # noqa: S101
        if not bot._skip_guild(interaction.guild):  # noqa: SLF001
            await interaction.response.send_message("ボイスチャンネルに接続していません")
            return
        await interaction.response.send_message("現在の読み上げをスキップしました")

    @tree.command(name="s", description="現在の読み上げをスキップします")
    @app_commands.guild_only()
    async def s(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None  # noqa: S101
        if not bot._skip_guild(interaction.guild):  # noqa: SLF001
            await interaction.response.send_message("ボイスチャンネルに接続していません")
            return
        await interaction.response.send_message("現在の読み上げをスキップしました")

    dict_group = app_commands.Group(name="dict", description="サーバー辞書の管理")

    @dict_group.command(name="add", description="単語を辞書に追加（サーバー管理権限が必要）")
    @app_commands.describe(word="単語", reading="読み方", regex="正規表現として扱うか")
    @app_commands.guild_only()
    @require_manage_guild
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
            f"単語を辞書に追加しました\n単語: `{word}`\n読み: `{reading}`\n正規表現: `{regex}`",
        )

    @dict_group.command(name="remove", description="単語を辞書から削除（サーバー管理権限が必要）")
    @app_commands.describe(word="単語")
    @app_commands.guild_only()
    @require_manage_guild
    async def dict_remove(interaction: discord.Interaction, word: str) -> None:
        assert interaction.guild is not None  # noqa: S101
        deleted = bot.database.delete_server_dict_entry(
            interaction.guild.id,
            bot.settings.bot_id,
            word,
        )
        if deleted:
            await interaction.response.send_message(
                f"単語を辞書から削除しました\n削除した単語: `{word}`",
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
            f"{index}. `{word}` -> `{reading}` (regex: `{regex}`)"
            for index, (word, reading, regex) in enumerate(entries, start=1)
        ]
        await interaction.response.send_message("\n".join(lines[:MAX_DICT_ENTRIES]))

    tree.add_command(dict_group)

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
        description="メンションやDiscordチャンネルURLの読み方を変更（サーバー管理権限が必要）",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="名前/チャンネル名", value="name"),
            app_commands.Choice(name="リンク省略", value="omit"),
        ],
    )
    @app_commands.guild_only()
    @require_manage_guild
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
        description="読み上げ前に投稿者名を読むか変更（サーバー管理権限が必要）",
    )
    @app_commands.guild_only()
    @require_manage_guild
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
        name="default_speaker",
        description="デフォルト話者IDを変更（サーバー管理権限が必要）",
    )
    @app_commands.guild_only()
    @require_manage_guild
    async def settings_default_speaker(
        interaction: discord.Interaction,
        speaker_id: SPEAKER_ID_INPUT_RANGE,
    ) -> None:
        assert interaction.guild is not None  # noqa: S101
        if not bot.synthesizer.is_style_available(speaker_id):
            await interaction.response.send_message(
                f"話者ID `{speaker_id}` は現在ロードされているVOICEVOXモデルにありません",
            )
            return

        bot.database.set_default_speaker_id(interaction.guild.id, bot.settings.bot_id, speaker_id)
        await interaction.response.send_message(f"デフォルト話者IDを `{speaker_id}` にしました")

    @settings_group.command(
        name="user_speaker",
        description="ユーザーごとの話者IDを設定（他人を変更するにはサーバー管理権限が必要）",
    )
    @app_commands.guild_only()
    async def settings_user_speaker(
        interaction: discord.Interaction,
        user: discord.Member,
        speaker_id: SPEAKER_ID_INPUT_RANGE,
    ) -> None:
        assert interaction.guild is not None  # noqa: S101
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "このコマンドはサーバー内でのみ使用できます",
            )
            return

        is_self = user.id == interaction.user.id
        if not is_self and not _has_manage_guild(interaction.user):
            await interaction.response.send_message(
                "他のユーザーの話者を変更するには「サーバーの管理」権限が必要です",
            )
            return

        if not bot.synthesizer.is_style_available(speaker_id):
            await interaction.response.send_message(
                f"話者ID `{speaker_id}` は現在ロードされているVOICEVOXモデルにありません",
            )
            return

        bot.database.set_user_speaker_id(
            interaction.guild.id,
            bot.settings.bot_id,
            user.id,
            speaker_id,
        )
        await interaction.response.send_message(
            f"{user.display_name} の話者IDを `{speaker_id}` にしました",
        )

    @settings_group.command(
        name="clear_user_speaker",
        description="ユーザーごとの話者IDを解除（他人を変更するにはサーバー管理権限が必要）",
    )
    @app_commands.guild_only()
    async def settings_clear_user_speaker(
        interaction: discord.Interaction,
        user: discord.Member,
    ) -> None:
        assert interaction.guild is not None  # noqa: S101
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "このコマンドはサーバー内でのみ使用できます",
            )
            return

        is_self = user.id == interaction.user.id
        if not is_self and not _has_manage_guild(interaction.user):
            await interaction.response.send_message(
                "他のユーザーの話者を変更するには「サーバーの管理」権限が必要です",
            )
            return

        bot.database.delete_user_speaker_id(interaction.guild.id, bot.settings.bot_id, user.id)
        await interaction.response.send_message(f"{user.display_name} の話者設定を解除しました")

    tree.add_command(settings_group)
