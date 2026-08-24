from __future__ import annotations

import contextlib
import logging
import re
import signal
from collections import OrderedDict
from collections.abc import Iterator

from yomiage.database import Database, DictEntry

LOGGER = logging.getLogger(__name__)

EN_PATTERN = re.compile(r"[a-z]+|[A-Z]{3,}|[A-Z][a-z]+")
UNICODE_FILTER = re.compile(r"[\U00010000-\U0010ffff]")
SPEAKABLE_PATTERN = re.compile(r"[0-9A-Za-zぁ-んァ-ヶー一-龯々〆〤]")
MAX_SPEAK_TEXT_LENGTH = 80
MAX_SOURCE_TEXT_LENGTH = 512
REGEX_TIMEOUT_SECONDS = 0.5
COMPILED_REGEX_CACHE_SIZE = 256


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
        result = result.replace(f"({index})", value or "")
    return result


def has_speakable_content(text: str) -> bool:
    return SPEAKABLE_PATTERN.search(UNICODE_FILTER.sub("", text)) is not None


class _RegexTimeoutError(Exception):
    """Raised when a user-supplied regex substitution runs too long."""


def _alarm_handler(_signum: int, _frame: object) -> None:
    raise _RegexTimeoutError


@contextlib.contextmanager
def _regex_time_limit(seconds: float) -> Iterator[None]:
    sigalrm = getattr(signal, "SIGALRM", None)
    if sigalrm is None:
        yield
        return

    previous_handler = signal.signal(sigalrm, _alarm_handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(sigalrm, previous_handler)


class Translator:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._compiled_regex_cache: OrderedDict[str, re.Pattern[str] | None] = OrderedDict()

    def convert(self, source_text: str, server_id: int, bot_id: int) -> str:
        speak_text = self._full_to_half(source_text[:MAX_SOURCE_TEXT_LENGTH])
        speak_text, protected_replacements = self._apply_protected_server_dict(
            speak_text,
            self.database.get_server_dict(server_id, bot_id),
        )
        speak_text = self._apply_dict(speak_text, self.database.get_global_dict())
        speak_text = self._apply_english(speak_text)
        speak_text = self._restore_protected_replacements(speak_text, protected_replacements)

        speak_text = UNICODE_FILTER.sub("", speak_text)
        if len(speak_text) > MAX_SPEAK_TEXT_LENGTH:
            speak_text = f"{speak_text[:MAX_SPEAK_TEXT_LENGTH]}いかりゃく"
        return speak_text.strip().replace(" ", "")

    def _full_to_half(self, source: str) -> str:
        return "".join(
            chr(ord(character) - 0xFEE0)
            if "\uff01" <= character <= "\uff5e"
            else character
            for character in source
        )

    def _compile_regex(self, pattern: str) -> re.Pattern[str] | None:
        cached = self._compiled_regex_cache.get(pattern)
        if cached is not None or pattern in self._compiled_regex_cache:
            self._compiled_regex_cache.move_to_end(pattern)
            return cached

        try:
            compiled = re.compile(pattern)
        except re.error:
            LOGGER.exception("Invalid regex dictionary entry skipped: %r", pattern)
            compiled = None

        self._compiled_regex_cache[pattern] = compiled
        while len(self._compiled_regex_cache) > COMPILED_REGEX_CACHE_SIZE:
            self._compiled_regex_cache.popitem(last=False)
        return compiled

    def _apply_dict(self, source: str, entries: list[DictEntry]) -> str:
        result = source
        for word, reading, is_regex in entries:
            if not is_regex:
                result = result.replace(word, reading)
                continue

            compiled = self._compile_regex(word)
            if compiled is None:
                continue
            try:
                with _regex_time_limit(REGEX_TIMEOUT_SECONDS):
                    result = compiled.sub(
                        lambda match, current_reading=reading: _replacement(
                            current_reading,
                            match,
                        ),
                        result,
                    )
            except _RegexTimeoutError:
                LOGGER.warning("Regex dictionary entry timed out and was skipped: %r", word)
        return result

    def _apply_protected_server_dict(
        self,
        source: str,
        entries: list[DictEntry],
    ) -> tuple[str, dict[str, str]]:
        replacements: dict[str, str] = {}
        result = source
        replacement_index = 0

        def replacement_token(reading: str, match: re.Match[str] | None = None) -> str:
            nonlocal replacement_index
            replacement = reading if match is None else _replacement(reading, match)
            token = f"\0{replacement_index}\0"
            replacement_index += 1
            replacements[token] = replacement
            return token

        for word, reading, is_regex in entries:
            if not is_regex:
                if word in result:
                    result = result.replace(word, replacement_token(reading))
                continue

            compiled = self._compile_regex(word)
            if compiled is None:
                continue
            try:
                with _regex_time_limit(REGEX_TIMEOUT_SECONDS):
                    result = compiled.sub(
                        lambda match, current_reading=reading: replacement_token(
                            current_reading,
                            match,
                        ),
                        result,
                    )
            except _RegexTimeoutError:
                LOGGER.warning("Regex dictionary entry timed out and was skipped: %r", word)
        return result, replacements

    def _restore_protected_replacements(self, source: str, replacements: dict[str, str]) -> str:
        result = source
        for token, replacement in replacements.items():
            result = result.replace(token, replacement)
        return result

    def _apply_english(self, source: str) -> str:
        entries = {key.lower(): reading for key, reading in self.database.get_en_dict()}

        def replace_token(match: re.Match[str]) -> str:
            word = match.group(0)
            reading = entries.get(word.lower())
            return reading if reading is not None else self._romaji_kana(word.lower())

        return EN_PATTERN.sub(replace_token, source)

    def _romaji_kana(self, source: str) -> str:
        result = source
        for key, value in KANA_TABLE:
            result = result.replace(key, value)
        return result
