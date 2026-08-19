"""Persistence layer backed by SQLite, with an in-memory cache for hot-path reads.

Guild settings and dictionaries change rarely compared to how often they are read
(once per chat message), so they are cached in memory and invalidated whenever the
underlying row is written. This keeps the design simple (no extra async DB driver)
while avoiding a SQLite round trip for every message.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

DictEntry = tuple[str, str, bool]
MentionReadMode = str
SqliteCursor = sqlite3.Cursor

DEFAULT_MENTION_READ_MODE: MentionReadMode = "name"
DEFAULT_READ_AUTHOR_NAME = True


@dataclass(frozen=True)
class GuildSettings:
    mention_read_mode: MentionReadMode
    read_author_name: bool
    default_speaker_id: int


DEFAULT_GLOBAL_DICT: tuple[DictEntry, ...] = (
    (r"(\d{1,2}):(\d{2})", r"(1)じ(2)ふん", True),
    (r"\(.*?\)", "", True),
    (r"(https?://\S+)(\s|$)", "りんくしょうりゃく", True),
    (r"(?s)`{1,3}[^`\n]+`{1,3}", "こーどしょうりゃく", True),
)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row

        self._guild_settings_cache: dict[tuple[int, int], GuildSettings] = {}
        self._server_dict_cache: dict[tuple[int, int], list[DictEntry]] = {}
        self._global_dict_cache: list[DictEntry] | None = None
        self._en_dict_cache: list[tuple[str, str]] | None = None

        self._init_schema()

    def close(self) -> None:
        self._connection.close()

    def _init_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS en_dict (
                word TEXT PRIMARY KEY,
                reading TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS global_dict (
                word TEXT PRIMARY KEY,
                reading TEXT NOT NULL,
                regex INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS server_dict (
                server_id INTEGER NOT NULL,
                bot_id INTEGER NOT NULL,
                word TEXT NOT NULL,
                reading TEXT NOT NULL,
                regex INTEGER NOT NULL DEFAULT 0,
                UNIQUE (server_id, bot_id, word)
            );

            CREATE TABLE IF NOT EXISTS guild_settings (
                server_id INTEGER NOT NULL,
                bot_id INTEGER NOT NULL,
                mention_read_mode TEXT NOT NULL,
                read_author_name INTEGER NOT NULL,
                default_speaker_id INTEGER NOT NULL,
                PRIMARY KEY (server_id, bot_id)
            );

            CREATE TABLE IF NOT EXISTS user_speakers (
                server_id INTEGER NOT NULL,
                bot_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                speaker_id INTEGER NOT NULL,
                PRIMARY KEY (server_id, bot_id, user_id)
            );
            """,
        )
        row = self._connection.execute("SELECT COUNT(*) AS count FROM global_dict").fetchone()
        if row is not None and row["count"] == 0:
            self.insert_global_entries(DEFAULT_GLOBAL_DICT)
        self._connection.commit()

    def insert_global_entries(self, entries: Iterable[DictEntry]) -> None:
        self._connection.executemany(
            """
            INSERT OR REPLACE INTO global_dict (word, reading, regex)
            VALUES (?, ?, ?)
            """,
            [(word, reading, int(regex)) for word, reading, regex in entries],
        )
        self._connection.commit()
        self._global_dict_cache = None

    def insert_en_dict_entries(self, entries: Iterable[tuple[str, str]]) -> None:
        self._connection.executemany(
            "INSERT OR REPLACE INTO en_dict (word, reading) VALUES (?, ?)",
            list(entries),
        )
        self._connection.commit()
        self._en_dict_cache = None

    def _finish_write(self, cursor: SqliteCursor) -> bool:
        changed = cursor.rowcount > 0
        if changed:
            self._connection.commit()
        elif self._connection.in_transaction:
            self._connection.rollback()
        return changed

    def get_en_dict(self) -> list[tuple[str, str]]:
        if self._en_dict_cache is None:
            rows = self._connection.execute("SELECT word, reading FROM en_dict").fetchall()
            self._en_dict_cache = [(row["word"], row["reading"]) for row in rows]
        return self._en_dict_cache

    def get_global_dict(self) -> list[DictEntry]:
        if self._global_dict_cache is None:
            rows = self._connection.execute(
                "SELECT word, reading, regex FROM global_dict",
            ).fetchall()
            self._global_dict_cache = [
                (row["word"], row["reading"], bool(row["regex"])) for row in rows
            ]
        return self._global_dict_cache

    def get_server_dict(self, server_id: int, bot_id: int) -> list[DictEntry]:
        key = (server_id, bot_id)
        cached = self._server_dict_cache.get(key)
        if cached is None:
            rows = self._connection.execute(
                """
                SELECT word, reading, regex
                FROM server_dict
                WHERE server_id = ? AND bot_id = ?
                ORDER BY word
                """,
                (server_id, bot_id),
            ).fetchall()
            cached = [(row["word"], row["reading"], bool(row["regex"])) for row in rows]
            self._server_dict_cache[key] = cached
        return cached

    def insert_server_dict_entry(
        self,
        server_id: int,
        bot_id: int,
        word: str,
        reading: str,
        regex: bool,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO server_dict (server_id, bot_id, word, reading, regex)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(server_id, bot_id, word)
            DO UPDATE SET reading = excluded.reading, regex = excluded.regex
            """,
            (server_id, bot_id, word, reading, int(regex)),
        )
        self._connection.commit()
        self._server_dict_cache.pop((server_id, bot_id), None)

    def delete_server_dict_entry(self, server_id: int, bot_id: int, word: str) -> bool:
        cursor = self._connection.execute(
            "DELETE FROM server_dict WHERE server_id = ? AND bot_id = ? AND word = ?",
            (server_id, bot_id, word),
        )
        deleted = self._finish_write(cursor)
        if deleted:
            self._server_dict_cache.pop((server_id, bot_id), None)
        return deleted

    def get_guild_settings(
        self,
        server_id: int,
        bot_id: int,
        fallback_speaker_id: int,
    ) -> GuildSettings:
        key = (server_id, bot_id)
        cached = self._guild_settings_cache.get(key)
        if cached is not None:
            return cached

        row = self._connection.execute(
            """
            SELECT mention_read_mode, read_author_name, default_speaker_id
            FROM guild_settings
            WHERE server_id = ? AND bot_id = ?
            """,
            (server_id, bot_id),
        ).fetchone()
        if row is None:
            settings = GuildSettings(
                mention_read_mode=DEFAULT_MENTION_READ_MODE,
                read_author_name=DEFAULT_READ_AUTHOR_NAME,
                default_speaker_id=fallback_speaker_id,
            )
        else:
            settings = GuildSettings(
                mention_read_mode=row["mention_read_mode"],
                read_author_name=bool(row["read_author_name"]),
                default_speaker_id=row["default_speaker_id"],
            )
        self._guild_settings_cache[key] = settings
        return settings

    def _ensure_guild_settings_row(
        self,
        server_id: int,
        bot_id: int,
        fallback_speaker_id: int,
    ) -> None:
        """Create the guild_settings row if missing, using the app-configured default speaker.

        This avoids the SQLite column default silently overriding the
        application's configured VOICEVOX_SPEAKER_ID when a row gets created as
        a side effect of changing some other, unrelated setting first.
        """
        self._connection.execute(
            """
            INSERT INTO guild_settings
                (server_id, bot_id, mention_read_mode, read_author_name, default_speaker_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(server_id, bot_id) DO NOTHING
            """,
            (
                server_id,
                bot_id,
                DEFAULT_MENTION_READ_MODE,
                int(DEFAULT_READ_AUTHOR_NAME),
                fallback_speaker_id,
            ),
        )

    def set_mention_read_mode(
        self,
        server_id: int,
        bot_id: int,
        mode: MentionReadMode,
        fallback_speaker_id: int,
    ) -> None:
        self._ensure_guild_settings_row(server_id, bot_id, fallback_speaker_id)
        self._connection.execute(
            "UPDATE guild_settings SET mention_read_mode = ? WHERE server_id = ? AND bot_id = ?",
            (mode, server_id, bot_id),
        )
        self._connection.commit()
        self._guild_settings_cache.pop((server_id, bot_id), None)

    def set_read_author_name(
        self,
        server_id: int,
        bot_id: int,
        enabled: bool,
        fallback_speaker_id: int,
    ) -> None:
        self._ensure_guild_settings_row(server_id, bot_id, fallback_speaker_id)
        self._connection.execute(
            "UPDATE guild_settings SET read_author_name = ? WHERE server_id = ? AND bot_id = ?",
            (int(enabled), server_id, bot_id),
        )
        self._connection.commit()
        self._guild_settings_cache.pop((server_id, bot_id), None)

    def set_default_speaker_id(self, server_id: int, bot_id: int, speaker_id: int) -> None:
        self._ensure_guild_settings_row(server_id, bot_id, speaker_id)
        self._connection.execute(
            "UPDATE guild_settings SET default_speaker_id = ? WHERE server_id = ? AND bot_id = ?",
            (speaker_id, server_id, bot_id),
        )
        self._connection.commit()
        self._guild_settings_cache.pop((server_id, bot_id), None)

    def get_user_speaker_id(self, server_id: int, bot_id: int, user_id: int) -> int | None:
        row = self._connection.execute(
            """
            SELECT speaker_id
            FROM user_speakers
            WHERE server_id = ? AND bot_id = ? AND user_id = ?
            """,
            (server_id, bot_id, user_id),
        ).fetchone()
        return None if row is None else row["speaker_id"]

    def set_user_speaker_id(
        self,
        server_id: int,
        bot_id: int,
        user_id: int,
        speaker_id: int,
    ) -> None:
        cursor = self._connection.execute(
            """
            INSERT INTO user_speakers (server_id, bot_id, user_id, speaker_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(server_id, bot_id, user_id)
            DO UPDATE SET speaker_id = excluded.speaker_id
            WHERE speaker_id IS NOT excluded.speaker_id
            """,
            (server_id, bot_id, user_id, speaker_id),
        )
        self._finish_write(cursor)

    def delete_user_speaker_id(self, server_id: int, bot_id: int, user_id: int) -> bool:
        cursor = self._connection.execute(
            """
            DELETE FROM user_speakers
            WHERE server_id = ? AND bot_id = ? AND user_id = ?
            """,
            (server_id, bot_id, user_id),
        )
        return self._finish_write(cursor)
