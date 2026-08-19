from __future__ import annotations

from pathlib import Path

import pytest

from yomiage.database import Database
from yomiage.translator import MAX_SPEAK_TEXT_LENGTH, Translator

SERVER_ID = 111
BOT_ID = 0


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "test.sqlite3")
    yield db
    db.close()


@pytest.fixture
def translator(database: Database) -> Translator:
    return Translator(database)


def test_plain_text_passes_through(translator: Translator) -> None:
    assert translator.convert("こんにちは", SERVER_ID, BOT_ID) == "こんにちは"


def test_global_dictionary_replacement(translator: Translator, database: Database) -> None:
    database.insert_global_entries([("VOICEVOX", "ボイスボックス", False)])
    assert translator.convert("VOICEVOXを使う", SERVER_ID, BOT_ID) == "ボイスボックスを使う"


def test_server_dictionary_replacement(translator: Translator, database: Database) -> None:
    database.insert_server_dict_entry(SERVER_ID, BOT_ID, "草", "くさ", False)
    assert translator.convert("草生える", SERVER_ID, BOT_ID) == "くさ生える"


def test_server_dictionary_overrides_global(translator: Translator, database: Database) -> None:
    database.insert_global_entries([("草", "そう", False)])
    database.insert_server_dict_entry(SERVER_ID, BOT_ID, "草", "くさ", True)
    assert translator.convert("草", SERVER_ID, BOT_ID) == "くさ"


def test_server_dictionary_replacement_is_not_rewritten_by_global(
    translator: Translator,
    database: Database,
) -> None:
    database.insert_global_entries([("くさ", "そう", False)])
    database.insert_server_dict_entry(SERVER_ID, BOT_ID, "草", "くさ", False)
    assert translator.convert("草", SERVER_ID, BOT_ID) == "くさ"


def test_regex_capture_group(translator: Translator, database: Database) -> None:
    database.insert_server_dict_entry(SERVER_ID, BOT_ID, r"(\d+)円", r"(1)えん", True)
    assert translator.convert("100円です", SERVER_ID, BOT_ID) == "100えんです"


def test_regex_optional_capture_group_does_not_crash(
    translator: Translator,
    database: Database,
) -> None:
    database.insert_server_dict_entry(SERVER_ID, BOT_ID, r"a(b)?(c)?", r"[(1)/(2)]", True)
    assert translator.convert("a", SERVER_ID, BOT_ID) == "[/]"


def test_url_is_shortened(translator: Translator) -> None:
    assert translator.convert("見て https://example.com/foo", SERVER_ID, BOT_ID) == (
        "見てりんくしょうりゃく"
    )


def test_code_block_is_shortened(translator: Translator) -> None:
    assert translator.convert("実行: `print(1)`", SERVER_ID, BOT_ID) == "実行:こーどしょうりゃく"


def test_english_dictionary_word(translator: Translator, database: Database) -> None:
    database.insert_en_dict_entries([("hello", "はろー")])
    assert translator.convert("hello", SERVER_ID, BOT_ID) == "はろー"


def test_romaji_conversion_for_unregistered_word(translator: Translator) -> None:
    assert translator.convert("ohayo", SERVER_ID, BOT_ID) == "おはよ"


def test_english_dictionary_and_romaji_combine_in_one_sentence(
    translator: Translator,
    database: Database,
) -> None:
    database.insert_en_dict_entries([("hello", "はろー")])
    assert translator.convert("hello sekai", SERVER_ID, BOT_ID) == "はろーせかい"


def test_long_text_is_truncated(translator: Translator) -> None:
    text = "あ" * (MAX_SPEAK_TEXT_LENGTH + 20)
    result = translator.convert(text, SERVER_ID, BOT_ID)
    assert result == "あ" * MAX_SPEAK_TEXT_LENGTH + "いかりゃく"


def test_unicode_surrogate_pairs_are_filtered(translator: Translator) -> None:
    assert translator.convert("絵文字😀テスト", SERVER_ID, BOT_ID) == "絵文字テスト"


def test_hyphen_in_normal_text_is_preserved(translator: Translator) -> None:
    assert translator.convert("あ-い", SERVER_ID, BOT_ID) == "あ-い"


def test_bracket_removal_does_not_strip_unrelated_hyphens(translator: Translator) -> None:
    assert translator.convert("あ(注釈)-い", SERVER_ID, BOT_ID) == "あ-い"


def test_empty_text_returns_empty(translator: Translator) -> None:
    assert translator.convert("", SERVER_ID, BOT_ID) == ""


def test_invalid_regex_entry_is_skipped_without_crashing(
    translator: Translator,
    database: Database,
) -> None:
    database.insert_server_dict_entry(SERVER_ID, BOT_ID, "(unclosed", "x", True)
    assert translator.convert("テスト", SERVER_ID, BOT_ID) == "テスト"
