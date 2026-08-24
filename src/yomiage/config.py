"""Application configuration loaded from environment variables.

Values are validated eagerly so misconfiguration fails fast at startup instead of
silently falling back to defaults or failing later during message handling.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

MAX_TOKENS_UPPER_BOUND = 100_000
VOICEVOX_CACHE_SIZE_UPPER_BOUND = 100_000
VOICEVOX_SPEED_UPPER_BOUND = 10.0
VOICEVOX_SPEAKER_ID_UPPER_BOUND = 100_000
BOT_ID_UPPER_BOUND = 2**63 - 1


class ConfigError(RuntimeError):
    """Raised when an environment variable has an invalid value."""


def _parse_int(name: str, raw: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _parse_float(name: str, raw: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw is None else _parse_int(name, raw)


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw is None else _parse_float(name, raw)


def _require_range(
    name: str,
    value: float,
    *,
    minimum: float | None = None,
    exclusive_minimum: float | None = None,
    maximum: float | None = None,
) -> None:
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}")
    if exclusive_minimum is not None and value <= exclusive_minimum:
        raise ConfigError(f"{name} must be > {exclusive_minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} must be <= {maximum}, got {value}")


@dataclass(frozen=True)
class Settings:
    discord_token: str
    bot_id: int
    database_path: Path
    max_tokens: int
    speaker_id: int
    speed: float
    voicevox_onnxruntime_path: Path
    open_jtalk_dict_dir: Path
    voicevox_model_path: Path
    cache_size: int
    ffmpeg_path: str

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        token = os.getenv("DISCORD_BOT_TOKEN")
        if not token:
            raise ConfigError(
                "DISCORD_BOT_TOKEN is required. Create .env from .env.example "
                "or export DISCORD_BOT_TOKEN before running.",
            )

        bot_id = _get_int("BOT_ID", 0)
        _require_range("BOT_ID", bot_id, minimum=0, maximum=BOT_ID_UPPER_BOUND)

        max_tokens = _get_int("MAX_TOKENS", 400)
        _require_range(
            "MAX_TOKENS",
            max_tokens,
            exclusive_minimum=0,
            maximum=MAX_TOKENS_UPPER_BOUND,
        )

        speaker_id = _get_int("VOICEVOX_SPEAKER_ID", 3)
        _require_range(
            "VOICEVOX_SPEAKER_ID",
            speaker_id,
            minimum=0,
            maximum=VOICEVOX_SPEAKER_ID_UPPER_BOUND,
        )

        speed = _get_float("VOICEVOX_SPEED", 1.2)
        _require_range(
            "VOICEVOX_SPEED",
            speed,
            exclusive_minimum=0,
            maximum=VOICEVOX_SPEED_UPPER_BOUND,
        )

        cache_size = _get_int("VOICEVOX_CACHE_SIZE", 100)
        _require_range(
            "VOICEVOX_CACHE_SIZE",
            cache_size,
            minimum=0,
            maximum=VOICEVOX_CACHE_SIZE_UPPER_BOUND,
        )

        return cls(
            discord_token=token,
            bot_id=bot_id,
            database_path=Path(os.getenv("YOMIAGE_DB", "yomiage.sqlite3")),
            max_tokens=max_tokens,
            speaker_id=speaker_id,
            speed=speed,
            voicevox_onnxruntime_path=Path(
                os.getenv(
                    "VOICEVOX_ONNXRUNTIME_PATH",
                    "./voicevox_core/onnxruntime/lib/libvoicevox_onnxruntime.so.1.17.3",
                ),
            ),
            open_jtalk_dict_dir=Path(
                os.getenv(
                    "OPEN_JTALK_DIC_DIR",
                    "./voicevox_core/dict/open_jtalk_dic_utf_8-1.11",
                ),
            ),
            voicevox_model_path=Path(
                os.getenv("VOICEVOX_MODEL_PATH", "./voicevox_core/models/vvms"),
            ),
            cache_size=cache_size,
            ffmpeg_path=os.getenv("FFMPEG_PATH", "ffmpeg"),
        )
