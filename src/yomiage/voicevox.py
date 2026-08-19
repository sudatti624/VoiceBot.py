from __future__ import annotations

import shutil
from collections import OrderedDict
from threading import Lock
from typing import Protocol, runtime_checkable

from voicevox_core.blocking import Onnxruntime, OpenJtalk, Synthesizer, VoiceModelFile

from yomiage.config import Settings

CacheKey = tuple[str, int, int]


class VoicevoxConfigError(RuntimeError):
    """Raised when the VOICEVOX runtime environment is misconfigured."""


@runtime_checkable
class SynthesizerLike(Protocol):
    """Interface the rest of the app depends on, so tests can supply a fake."""

    def generate(self, text: str, speaker_id: int | None = None) -> bytes: ...

    def is_style_available(self, style_id: int) -> bool: ...

    def available_style_ids(self) -> frozenset[int]: ...


class VoicevoxSynthesizer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cache: OrderedDict[CacheKey, bytes] = OrderedDict()
        self._lock = Lock()

        runtime = Onnxruntime.load_once(filename=str(settings.voicevox_onnxruntime_path))
        open_jtalk = OpenJtalk(settings.open_jtalk_dict_dir)
        self._synthesizer = Synthesizer(runtime, open_jtalk, cpu_num_threads=4)
        model = VoiceModelFile.open(settings.voicevox_model_path)
        self._synthesizer.load_voice_model(model)
        self._style_ids = frozenset(
            int(style.id)
            for character in self._synthesizer.metas()
            for style in character.styles
        )

    def generate(self, text: str, speaker_id: int | None = None) -> bytes:
        style_id = speaker_id if speaker_id is not None else self.settings.speaker_id
        key = (text, style_id, int(self.settings.speed * 100))
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached

            audio_query = self._synthesizer.create_audio_query(text, style_id)
            audio_query.speed_scale = self.settings.speed
            wav_data = self._synthesizer.synthesis(audio_query, style_id)

            self._cache[key] = wav_data
            while len(self._cache) > self.settings.cache_size:
                self._cache.popitem(last=False)
            return wav_data

    def is_style_available(self, style_id: int) -> bool:
        return style_id in self._style_ids

    def available_style_ids(self) -> frozenset[int]:
        return self._style_ids


def validate_environment(settings: Settings) -> None:
    """Validate that VOICEVOX files and ffmpeg are actually usable before startup."""
    if not settings.voicevox_onnxruntime_path.is_file():
        raise VoicevoxConfigError(
            f"VOICEVOX_ONNXRUNTIME_PATH must be a file: {settings.voicevox_onnxruntime_path}",
        )
    if not settings.open_jtalk_dict_dir.is_dir():
        raise VoicevoxConfigError(
            f"OPEN_JTALK_DIC_DIR must be a directory: {settings.open_jtalk_dict_dir}",
        )
    if not settings.voicevox_model_path.is_file():
        raise VoicevoxConfigError(
            f"VOICEVOX_MODEL_PATH must be a file: {settings.voicevox_model_path}",
        )

    if shutil.which(settings.ffmpeg_path) is None:
        raise VoicevoxConfigError(
            f"ffmpeg executable not found: {settings.ffmpeg_path!r}. "
            "Install ffmpeg or set FFMPEG_PATH.",
        )


def validate_speaker_id(settings: Settings, synthesizer: SynthesizerLike) -> None:
    """Validate VOICEVOX_SPEAKER_ID against the styles available in the loaded model."""
    if not synthesizer.is_style_available(settings.speaker_id):
        raise VoicevoxConfigError(
            f"VOICEVOX_SPEAKER_ID={settings.speaker_id} is not available in the loaded "
            "VOICEVOX model. Check the available speaker/style IDs for your .vvm file.",
        )
