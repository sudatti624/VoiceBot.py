"""Per-utterance latency measurements, logged when ``VOICEVOX_PERFORMANCE_LOG=true``.

Every timestamp is a real ``time.perf_counter()`` reading taken where the event
happens; anything that was not observed (cache hit, cancellation, ...) is logged
as ``n/a`` rather than estimated. Times are milliseconds since the speech item was
picked up by the guild worker.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

LOGGER = logging.getLogger(__name__)


@dataclass
class SpeechMetrics:
    guild_id: int
    configured_mode: str
    # "normal", "streaming", "streaming->normal" (auto fallback) or "cache".
    path: str = "normal"
    cache_hit: bool | None = None
    outcome: str = "completed"
    underruns: int | None = None
    started_at: float = field(default_factory=time.perf_counter)
    synthesis_started_at: float | None = None
    first_audio_at: float | None = None
    synthesis_finished_at: float | None = None
    playback_started_at: float | None = None
    playback_finished_at: float | None = None

    def log(self) -> None:
        LOGGER.info(
            "speech_perf guild=%s mode=%s path=%s cache_hit=%s outcome=%s "
            "synthesis_start_ms=%s first_audio_ms=%s playback_start_ms=%s "
            "synthesis_total_ms=%s playback_end_ms=%s underruns=%s",
            self.guild_id,
            self.configured_mode,
            self.path,
            _fmt(self.cache_hit),
            self.outcome,
            self._since_start(self.synthesis_started_at),
            self._since_start(self.first_audio_at),
            self._since_start(self.playback_started_at),
            _duration(self.synthesis_started_at, self.synthesis_finished_at),
            self._since_start(self.playback_finished_at),
            _fmt(self.underruns),
        )

    def _since_start(self, value: float | None) -> str:
        return _duration(self.started_at, value)


def _duration(start: float | None, end: float | None) -> str:
    if start is None or end is None:
        return "n/a"
    return f"{(end - start) * 1000:.1f}"


def _fmt(value: object) -> str:
    return "n/a" if value is None else str(value).lower()
