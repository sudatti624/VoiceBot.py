from __future__ import annotations

import faulthandler
import logging
import sys

from yomiage.bot import make_bot
from yomiage.config import ConfigError, Settings
from yomiage.voicevox import (
    VoicevoxConfigError,
    discover_voice_model_paths,
    validate_environment,
    validate_speaker_id,
)

LOGGER = logging.getLogger(__name__)


def main() -> None:
    faulthandler.enable()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    LOGGER.info("Starting yomiage bot on Python %s", sys.version.replace("\n", " "))
    try:
        settings = Settings.from_env()
        LOGGER.info(
            "Configuration loaded: db=%s max_tokens=%s speaker_id=%s speed=%s "
            "acceleration=%s cache_size=%s ffmpeg=%s",
            settings.database_path,
            settings.max_tokens,
            settings.speaker_id,
            settings.speed,
            settings.voicevox_acceleration_mode,
            settings.cache_size,
            settings.ffmpeg_path,
        )
        LOGGER.info(
            "VOICEVOX paths: onnxruntime=%s open_jtalk_dict=%s model_path=%s",
            settings.voicevox_onnxruntime_path,
            settings.open_jtalk_dict_dir,
            settings.voicevox_model_path,
        )
        validate_environment(settings)
    except (ConfigError, VoicevoxConfigError):
        LOGGER.exception("Invalid configuration, refusing to start")
        raise

    model_paths = discover_voice_model_paths(settings.voicevox_model_path)
    LOGGER.info("Discovered %s VOICEVOX model candidate(s)", len(model_paths))
    for model_path in model_paths:
        LOGGER.info("VOICEVOX model candidate: %s", model_path)

    LOGGER.info("Loading VOICEVOX CORE")
    try:
        bot = make_bot(settings)
    except Exception:
        LOGGER.exception("Failed to initialize bot or VOICEVOX CORE")
        raise
    try:
        validate_speaker_id(settings, bot.synthesizer)
    except VoicevoxConfigError:
        LOGGER.exception("Invalid VOICEVOX_SPEAKER_ID, refusing to start")
        raise
    LOGGER.info(
        "VOICEVOX CORE loaded with %s available style ID(s)",
        len(bot.synthesizer.available_style_ids()),
    )

    LOGGER.info("Starting Discord client")
    try:
        bot.run(settings.discord_token)
    except Exception:
        LOGGER.exception("Discord client stopped with an exception")
        raise
    finally:
        LOGGER.info("Discord client stopped")
