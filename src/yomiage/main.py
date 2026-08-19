from __future__ import annotations

import logging

from yomiage.bot import make_bot
from yomiage.config import Settings
from yomiage.voicevox import validate_voicevox_paths


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_env()
    validate_voicevox_paths(settings)
    bot = make_bot(settings)
    bot.run(settings.discord_token)
