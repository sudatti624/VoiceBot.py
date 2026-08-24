from __future__ import annotations

from yomiage.voice_catalog import (
    VOICE_CATALOG,
    VOICE_LICENSE_PAGE_FIELD_LIMIT,
    VOICE_LICENSES,
    VOICE_LIST_PAGE_FIELD_LIMIT,
    format_voice_license,
    format_voice_styles,
    voice_catalog_pages,
    voice_license_pages,
)


def test_voice_catalog_contains_expected_entries() -> None:
    metan = next(
        entry for entry in VOICE_CATALOG if entry.vvm == "0.vvm" and entry.character == "四国めたん"
    )
    assert format_voice_styles(metan) == "あまあま `0` / ノーマル `2` / セクシー `4` / ツンツン `6`"

    yukari = next(entry for entry in VOICE_CATALOG if entry.character == "里石ユカ")
    assert yukari.vvm == "24.vvm"
    assert format_voice_styles(yukari) == "つぼみ `126`"


def test_voice_catalog_pages_fit_discord_embed_field_limit() -> None:
    pages = voice_catalog_pages()

    assert len(pages) > 1
    assert sum(len(page) for page in pages) == len(VOICE_CATALOG)
    assert all(1 <= len(page) <= VOICE_LIST_PAGE_FIELD_LIMIT for page in pages)


def test_voice_licenses_cover_catalog_characters() -> None:
    catalog_characters = {entry.character for entry in VOICE_CATALOG}
    licensed_characters = {entry.character for entry in VOICE_LICENSES}

    assert catalog_characters <= licensed_characters


def test_voice_license_contains_credit_and_terms_url() -> None:
    mochi = next(entry for entry in VOICE_LICENSES if entry.character == "もち子さん")
    formatted = format_voice_license(mochi)

    assert "VOICEVOX:もち子(cv 明日葉よもぎ)" in formatted
    assert "https://" in formatted
    assert "事前確認" in formatted


def test_voice_license_pages_fit_discord_embed_field_limit() -> None:
    pages = voice_license_pages()

    assert len(pages) > 1
    assert sum(len(page) for page in pages) == len(VOICE_LICENSES)
    assert all(1 <= len(page) <= VOICE_LICENSE_PAGE_FIELD_LIMIT for page in pages)
