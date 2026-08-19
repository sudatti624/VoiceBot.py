from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


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
            raise RuntimeError(
                "DISCORD_BOT_TOKEN is required. Create .env from .env.example "
                "or export DISCORD_BOT_TOKEN before running.",
            )

        return cls(
            discord_token=token,
            bot_id=_get_int("BOT_ID", 0),
            database_path=Path(os.getenv("YOMIAGE_DB", "yomiage.sqlite3")),
            max_tokens=_get_int("MAX_TOKENS", 400),
            speaker_id=_get_int("VOICEVOX_SPEAKER_ID", 3),
            speed=_get_float("VOICEVOX_SPEED", 1.2),
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
                os.getenv("VOICEVOX_MODEL_PATH", "./voicevox_core/models/vvms/0.vvm"),
            ),
            cache_size=_get_int("VOICEVOX_CACHE_SIZE", 100),
            ffmpeg_path=os.getenv("FFMPEG_PATH", "ffmpeg"),
        )
