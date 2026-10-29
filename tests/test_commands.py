from __future__ import annotations

from yomiage.commands import (
    DISCORD_MESSAGE_LIMIT,
    MAX_DICT_ENTRIES,
    MAX_DICT_READING_LENGTH,
    MAX_DICT_WORD_LENGTH,
    _build_voice_catalog_embeds,
    _build_voice_license_embeds,
    _chunk_lines,
    _inline_code,
)
from yomiage.voice_catalog import voice_catalog_pages, voice_license_pages


def test_inline_code_cannot_be_closed_by_user_text() -> None:
    rendered = _inline_code("a`@everyone`b")

    assert rendered.startswith("`")
    assert rendered.endswith("`")
    assert rendered.count("`") == 2


def test_chunk_lines_keeps_short_lists_in_one_message() -> None:
    assert _chunk_lines(["1", "2", "3"]) == ["1\n2\n3"]


def test_chunk_lines_splits_full_dictionary_under_discord_limit() -> None:
    word = "w" * MAX_DICT_WORD_LENGTH
    reading = "r" * MAX_DICT_READING_LENGTH
    lines = [
        f"{index}. {_inline_code(word)} -> {_inline_code(reading)} (regex: `False`)"
        for index in range(1, MAX_DICT_ENTRIES + 1)
    ]

    chunks = _chunk_lines(lines)

    assert len(chunks) > 1
    assert all(len(chunk) <= DISCORD_MESSAGE_LIMIT for chunk in chunks)
    assert "\n".join(chunks).splitlines() == lines


def test_chunk_lines_truncates_a_single_overlong_line() -> None:
    assert _chunk_lines(["x" * 30], limit=10) == ["x" * 10]


def test_paged_embeds_have_one_embed_per_page() -> None:
    catalog = _build_voice_catalog_embeds()
    licenses = _build_voice_license_embeds()

    assert len(catalog) == len(voice_catalog_pages())
    assert len(licenses) == len(voice_license_pages())
    assert catalog[0].title is not None
    assert catalog[0].title.endswith(f"(1/{len(catalog)})")
    assert licenses[0].description is not None
