from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

DictEntry = tuple[str, str, bool]
MentionReadMode = str
SqliteCursor = sqlite3.Cursor


class GuildSettings:
    def __init__(
        self,
        *,
        mention_read_mode: MentionReadMode,
        read_author_name: bool,
        default_speaker_id: int,
    ) -> None:
        self.mention_read_mode = mention_read_mode
        self.read_author_name = read_author_name
        self.default_speaker_id = default_speaker_id

DEFAULT_GLOBAL_DICT: tuple[DictEntry, ...] = (
    (r"(\d{1,2}):(\d{2})", r"(1)じ(2)ふん", True),
    (r"\(.*?\)", "-", True),
    (r"(https?://\S+)(\s|$)", "りんくしょうりゃく", True),
    (r"(?s)`{1,3}[^`\n]+`{1,3}", "こーどしょうりゃく", True),
)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
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
                mention_read_mode TEXT NOT NULL DEFAULT 'name',
                read_author_name INTEGER NOT NULL DEFAULT 1,
                default_speaker_id INTEGER NOT NULL DEFAULT 3,
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

    def _finish_write(self, cursor: SqliteCursor) -> None:
        if cursor.rowcount > 0:
            self._connection.commit()
        elif self._connection.in_transaction:
            self._connection.rollback()

    def get_en_dict(self) -> list[tuple[str, str]]:
        rows = self._connection.execute("SELECT word, reading FROM en_dict").fetchall()
        return [(row["word"], row["reading"]) for row in rows]

    def get_global_dict(self) -> list[DictEntry]:
        rows = self._connection.execute("SELECT word, reading, regex FROM global_dict").fetchall()
        return [(row["word"], row["reading"], bool(row["regex"])) for row in rows]

    def get_server_dict(self, server_id: int, bot_id: int) -> list[DictEntry]:
        rows = self._connection.execute(
            """
            SELECT word, reading, regex
            FROM server_dict
            WHERE server_id = ? AND bot_id = ?
            ORDER BY word
            """,
            (server_id, bot_id),
        ).fetchall()
        return [(row["word"], row["reading"], bool(row["regex"])) for row in rows]

    def insert_server_dict_entry(
        self,
        server_id: int,
        bot_id: int,
        word: str,
        reading: str,
        regex: bool,
    ) -> None:
        cursor = self._connection.execute(
            """
            INSERT INTO server_dict (server_id, bot_id, word, reading, regex)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(server_id, bot_id, word)
            DO UPDATE SET reading = excluded.reading, regex = excluded.regex
            WHERE reading IS NOT excluded.reading OR regex IS NOT excluded.regex
            """,
            (server_id, bot_id, word, reading, int(regex)),
        )
        self._finish_write(cursor)

    def delete_server_dict_entry(self, server_id: int, bot_id: int, word: str) -> None:
        cursor = self._connection.execute(
            "DELETE FROM server_dict WHERE server_id = ? AND bot_id = ? AND word = ?",
            (server_id, bot_id, word),
        )
        self._finish_write(cursor)

    def get_guild_settings(
        self,
        server_id: int,
        bot_id: int,
        fallback_speaker_id: int,
    ) -> GuildSettings:
        row = self._connection.execute(
            """
            SELECT mention_read_mode, read_author_name, default_speaker_id
            FROM guild_settings
            WHERE server_id = ? AND bot_id = ?
            """,
            (server_id, bot_id),
        ).fetchone()
        if row is None:
            return GuildSettings(
                mention_read_mode="name",
                read_author_name=True,
                default_speaker_id=fallback_speaker_id,
            )
        return GuildSettings(
            mention_read_mode=row["mention_read_mode"],
            read_author_name=bool(row["read_author_name"]),
            default_speaker_id=row["default_speaker_id"],
        )

    def set_mention_read_mode(self, server_id: int, bot_id: int, mode: MentionReadMode) -> None:
        cursor = self._connection.execute(
            """
            INSERT INTO guild_settings (server_id, bot_id, mention_read_mode)
            VALUES (?, ?, ?)
            ON CONFLICT(server_id, bot_id)
            DO UPDATE SET mention_read_mode = excluded.mention_read_mode
            WHERE mention_read_mode IS NOT excluded.mention_read_mode
            """,
            (server_id, bot_id, mode),
        )
        self._finish_write(cursor)

    def set_read_author_name(self, server_id: int, bot_id: int, enabled: bool) -> None:
        cursor = self._connection.execute(
            """
            INSERT INTO guild_settings (server_id, bot_id, read_author_name)
            VALUES (?, ?, ?)
            ON CONFLICT(server_id, bot_id)
            DO UPDATE SET read_author_name = excluded.read_author_name
            WHERE read_author_name IS NOT excluded.read_author_name
            """,
            (server_id, bot_id, int(enabled)),
        )
        self._finish_write(cursor)

    def set_default_speaker_id(self, server_id: int, bot_id: int, speaker_id: int) -> None:
        cursor = self._connection.execute(
            """
            INSERT INTO guild_settings (server_id, bot_id, default_speaker_id)
            VALUES (?, ?, ?)
            ON CONFLICT(server_id, bot_id)
            DO UPDATE SET default_speaker_id = excluded.default_speaker_id
            WHERE default_speaker_id IS NOT excluded.default_speaker_id
            """,
            (server_id, bot_id, speaker_id),
        )
        self._finish_write(cursor)

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

    def delete_user_speaker_id(self, server_id: int, bot_id: int, user_id: int) -> None:
        cursor = self._connection.execute(
            """
            DELETE FROM user_speakers
            WHERE server_id = ? AND bot_id = ? AND user_id = ?
            """,
            (server_id, bot_id, user_id),
        )
        self._finish_write(cursor)
