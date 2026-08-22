from __future__ import annotations

from pathlib import Path

import pytest

from yomiage.database import Database

SERVER_ID = 42
BOT_ID = 0
FALLBACK_SPEAKER = 7


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "test.sqlite3")
    yield db
    db.close()


def test_guild_settings_default_when_missing(database: Database) -> None:
    settings = database.get_guild_settings(SERVER_ID, BOT_ID, FALLBACK_SPEAKER)
    assert settings.mention_read_mode == "name"
    assert settings.read_author_name is True
    assert settings.default_speaker_id == FALLBACK_SPEAKER
    assert settings.server_chat_enabled is False


def test_fallback_speaker_used_when_row_created_by_other_setting(database: Database) -> None:
    database.set_read_author_name(
        SERVER_ID,
        BOT_ID,
        enabled=False,
        fallback_speaker_id=FALLBACK_SPEAKER,
    )
    settings = database.get_guild_settings(SERVER_ID, BOT_ID, FALLBACK_SPEAKER)
    assert settings.default_speaker_id == FALLBACK_SPEAKER
    assert settings.read_author_name is False


def test_changing_one_setting_does_not_break_others(database: Database) -> None:
    database.set_default_speaker_id(SERVER_ID, BOT_ID, 12)
    database.set_mention_read_mode(SERVER_ID, BOT_ID, "omit", FALLBACK_SPEAKER)
    database.set_read_author_name(
        SERVER_ID,
        BOT_ID,
        enabled=False,
        fallback_speaker_id=FALLBACK_SPEAKER,
    )

    settings = database.get_guild_settings(SERVER_ID, BOT_ID, FALLBACK_SPEAKER)
    assert settings.default_speaker_id == 12
    assert settings.mention_read_mode == "omit"
    assert settings.read_author_name is False
    assert settings.server_chat_enabled is False


def test_server_chat_enabled_round_trip(database: Database) -> None:
    database.set_server_chat_enabled(
        SERVER_ID,
        BOT_ID,
        enabled=True,
        fallback_speaker_id=FALLBACK_SPEAKER,
    )

    settings = database.get_guild_settings(SERVER_ID, BOT_ID, FALLBACK_SPEAKER)
    assert settings.server_chat_enabled is True


def test_guild_settings_cache_invalidated_on_write(database: Database) -> None:
    database.get_guild_settings(SERVER_ID, BOT_ID, FALLBACK_SPEAKER)
    database.set_default_speaker_id(SERVER_ID, BOT_ID, 99)
    settings = database.get_guild_settings(SERVER_ID, BOT_ID, FALLBACK_SPEAKER)
    assert settings.default_speaker_id == 99


def test_server_dict_upsert_updates_existing_entry(database: Database) -> None:
    database.insert_server_dict_entry(SERVER_ID, BOT_ID, "単語", "たんご", False)
    database.insert_server_dict_entry(SERVER_ID, BOT_ID, "単語", "たんご2", False)
    entries = database.get_server_dict(SERVER_ID, BOT_ID)
    assert entries == [("単語", "たんご2", False)]


def test_delete_existing_entry_returns_true(database: Database) -> None:
    database.insert_server_dict_entry(SERVER_ID, BOT_ID, "単語", "たんご", False)
    assert database.delete_server_dict_entry(SERVER_ID, BOT_ID, "単語") is True
    assert database.get_server_dict(SERVER_ID, BOT_ID) == []


def test_delete_missing_entry_returns_false(database: Database) -> None:
    assert database.delete_server_dict_entry(SERVER_ID, BOT_ID, "存在しない単語") is False


def test_user_speaker_round_trip(database: Database) -> None:
    assert database.get_user_speaker_id(SERVER_ID, BOT_ID, 1) is None
    database.set_user_speaker_id(SERVER_ID, BOT_ID, 1, 55)
    assert database.get_user_speaker_id(SERVER_ID, BOT_ID, 1) == 55


def test_delete_user_speaker_returns_whether_deleted(database: Database) -> None:
    assert database.delete_user_speaker_id(SERVER_ID, BOT_ID, 1) is False
    database.set_user_speaker_id(SERVER_ID, BOT_ID, 1, 55)
    assert database.delete_user_speaker_id(SERVER_ID, BOT_ID, 1) is True
    assert database.get_user_speaker_id(SERVER_ID, BOT_ID, 1) is None
