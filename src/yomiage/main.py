from __future__ import annotations

import logging

from yomiage.bot import make_bot
from yomiage.config import ConfigError, Settings
from yomiage.voicevox import VoicevoxConfigError, validate_environment, validate_speaker_id

LOGGER = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        settings = Settings.from_env()
        validate_environment(settings)
    except (ConfigError, VoicevoxConfigError):
        LOGGER.exception("Invalid configuration, refusing to start")
        raise

    LOGGER.info("Loading VOICEVOX CORE from %s", settings.voicevox_model_path)
    bot = make_bot(settings)
    try:
        validate_speaker_id(settings, bot.synthesizer)
    except VoicevoxConfigError:
        LOGGER.exception("Invalid VOICEVOX_SPEAKER_ID, refusing to start")
        raise
    LOGGER.info("VOICEVOX CORE loaded")

    bot.run(settings.discord_token)
