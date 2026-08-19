from __future__ import annotations

import re

from yomiage.database import Database, DictEntry

EN_PATTERN = re.compile(r"[a-z]+|[A-Z]{3,}|[A-Z][a-z]+")
ROMAJI_PATTERN = re.compile(r"[a-zA-Z]")
UNICODE_FILTER = re.compile(r"[\U00010000-\U0010ffff]")
MAX_SPEAK_TEXT_LENGTH = 80

KANA_TABLE: tuple[tuple[str, str], ...] = (
    ("kya", "きゃ"),
    ("kyu", "きゅ"),
    ("kyo", "きょ"),
    ("sha", "しゃ"),
    ("shu", "しゅ"),
    ("sho", "しょ"),
    ("cha", "ちゃ"),
    ("chu", "ちゅ"),
    ("cho", "ちょ"),
    ("tsu", "つ"),
    ("shi", "し"),
    ("chi", "ち"),
    ("rya", "りゃ"),
    ("ryu", "りゅ"),
    ("ryo", "りょ"),
    ("gya", "ぎゃ"),
    ("gyu", "ぎゅ"),
    ("gyo", "ぎょ"),
    ("ja", "じゃ"),
    ("ju", "じゅ"),
    ("jo", "じょ"),
    ("fa", "ふぁ"),
    ("fi", "ふぃ"),
    ("fe", "ふぇ"),
    ("fo", "ふぉ"),
    ("nn", "ん"),
    ("ka", "か"),
    ("ki", "き"),
    ("ku", "く"),
    ("ke", "け"),
    ("ko", "こ"),
    ("sa", "さ"),
    ("si", "し"),
    ("su", "す"),
    ("se", "せ"),
    ("so", "そ"),
    ("ta", "た"),
    ("ti", "ち"),
    ("tu", "つ"),
    ("te", "て"),
    ("to", "と"),
    ("na", "な"),
    ("ni", "に"),
    ("nu", "ぬ"),
    ("ne", "ね"),
    ("no", "の"),
    ("ha", "は"),
    ("hi", "ひ"),
    ("hu", "ふ"),
    ("he", "へ"),
    ("ho", "ほ"),
    ("ma", "ま"),
    ("mi", "み"),
    ("mu", "む"),
    ("me", "め"),
    ("mo", "も"),
    ("ya", "や"),
    ("yu", "ゆ"),
    ("yo", "よ"),
    ("ra", "ら"),
    ("ri", "り"),
    ("ru", "る"),
    ("re", "れ"),
    ("ro", "ろ"),
    ("wa", "わ"),
    ("wo", "を"),
    ("ga", "が"),
    ("gi", "ぎ"),
    ("gu", "ぐ"),
    ("ge", "げ"),
    ("go", "ご"),
    ("za", "ざ"),
    ("zi", "じ"),
    ("zu", "ず"),
    ("ze", "ぜ"),
    ("zo", "ぞ"),
    ("da", "だ"),
    ("di", "ぢ"),
    ("du", "づ"),
    ("de", "で"),
    ("do", "ど"),
    ("ba", "ば"),
    ("bi", "び"),
    ("bu", "ぶ"),
    ("be", "べ"),
    ("bo", "ぼ"),
    ("pa", "ぱ"),
    ("pi", "ぴ"),
    ("pu", "ぷ"),
    ("pe", "ぺ"),
    ("po", "ぽ"),
    ("a", "あ"),
    ("i", "い"),
    ("u", "う"),
    ("e", "え"),
    ("o", "お"),
    ("n", "ん"),
)


def _replacement(reading: str, match: re.Match[str]) -> str:
    result = reading
    for index, value in enumerate(match.groups(), start=1):
        result = result.replace(f"({index})", value)
    return result


class Translator:
    def __init__(self, database: Database) -> None:
        self.database = database

    def convert(self, source_text: str, server_id: int, bot_id: int) -> str:
        speak_text = self._full_to_half(source_text)
        speak_text = self._apply_dict(speak_text, self.database.get_global_dict())
        speak_text = self._apply_dict(speak_text, self.database.get_server_dict(server_id, bot_id))

        before_en = speak_text
        speak_text = self._apply_en_dict(speak_text)
        if speak_text == before_en and ROMAJI_PATTERN.search(speak_text):
            speak_text = self._romaji_kana(speak_text.lower())

        speak_text = UNICODE_FILTER.sub("", speak_text)
        if len(speak_text) > MAX_SPEAK_TEXT_LENGTH:
            speak_text = f"{speak_text[:MAX_SPEAK_TEXT_LENGTH]}いかりゃく"
        return speak_text.strip().replace("-", "").replace(" ", "")

    def _full_to_half(self, source: str) -> str:
        return "".join(
            chr(ord(character) - 0xFEE0)
            if "\uff01" <= character <= "\uff5e"
            else character
            for character in source
        )

    def _apply_dict(self, source: str, entries: list[DictEntry]) -> str:
        result = source
        for word, reading, is_regex in entries:
            if is_regex:
                try:
                    result = re.sub(
                        word,
                        lambda match, current_reading=reading: _replacement(
                            current_reading,
                            match,
                        ),
                        result,
                    )
                except re.error:
                    continue
            else:
                result = result.replace(word, reading)
        return result

    def _apply_en_dict(self, source: str) -> str:
        result = source
        entries = self.database.get_en_dict()
        for word in EN_PATTERN.findall(source):
            reading = next(
                (candidate for key, candidate in entries if key.lower() == word.lower()),
                None,
            )
            if reading is not None:
                result = result.replace(word, reading)
        return result

    def _romaji_kana(self, source: str) -> str:
        result = source
        for key, value in KANA_TABLE:
            result = result.replace(key, value)
        return result
