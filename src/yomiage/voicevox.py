from __future__ import annotations

import logging
import shutil
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Protocol, runtime_checkable

from voicevox_core.blocking import Onnxruntime, OpenJtalk, Synthesizer, VoiceModelFile

from yomiage.config import Settings

CacheKey = tuple[str, int, int]
VOICE_MODEL_GLOB = "*.vvm"
LOGGER = logging.getLogger(__name__)


class VoicevoxConfigError(RuntimeError):
    """Raised when the VOICEVOX runtime environment is misconfigured."""


def _is_excluded_voice_model(path: Path, excludes: tuple[str, ...]) -> bool:
    return any(exclude in {path.name, path.stem, str(path)} for exclude in excludes)


def _voice_model_sort_key(path: Path) -> tuple[int, int | str]:
    try:
        return (0, int(path.stem))
    except ValueError:
        return (1, path.name)


def discover_voice_model_paths(path: Path, excludes: tuple[str, ...] = ()) -> tuple[Path, ...]:
    """Return every VVM model that should be loaded for the configured path."""
    if path.is_dir():
        return tuple(
            model_path
            for model_path in sorted(path.glob(VOICE_MODEL_GLOB), key=_voice_model_sort_key)
            if not _is_excluded_voice_model(model_path, excludes)
        )
    if path.is_file():
        model_paths = tuple(sorted(path.parent.glob(VOICE_MODEL_GLOB), key=_voice_model_sort_key))
        return tuple(
            model_path
            for model_path in (model_paths or (path,))
            if not _is_excluded_voice_model(model_path, excludes)
        )
    return ()


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
        self._style_model_paths: dict[int, Path] = {}
        self._loaded_model_paths: set[Path] = set()

        LOGGER.info("Loading VOICEVOX ONNX Runtime: %s", settings.voicevox_onnxruntime_path)
        runtime = Onnxruntime.load_once(filename=str(settings.voicevox_onnxruntime_path))
        try:
            LOGGER.info("VOICEVOX supported devices: %r", runtime.supported_devices())
        except Exception:
            LOGGER.exception("Failed to query VOICEVOX supported devices")
        LOGGER.info("Loading OpenJTalk dictionary: %s", settings.open_jtalk_dict_dir)
        open_jtalk = OpenJtalk(settings.open_jtalk_dict_dir)
        LOGGER.info(
            "Creating VOICEVOX synthesizer: acceleration=%s cpu_threads=%s",
            settings.voicevox_acceleration_mode,
            4,
        )
        self._synthesizer = Synthesizer(
            runtime,
            open_jtalk,
            acceleration_mode=settings.voicevox_acceleration_mode,
            cpu_num_threads=4,
        )

        indexed_model_paths: list[Path] = []
        for model_path in discover_voice_model_paths(
            settings.voicevox_model_path,
            settings.voicevox_model_exclude,
        ):
            try:
                LOGGER.info("Opening VOICEVOX model metadata: %s", model_path)
                model = VoiceModelFile.open(model_path)
                for character in model.metas:
                    for style in character.styles:
                        self._style_model_paths[int(style.id)] = model_path
                model.close()
            except Exception:
                LOGGER.exception("Failed to read VOICEVOX model metadata, skipping: %s", model_path)
                continue
            indexed_model_paths.append(model_path)
            LOGGER.info("Indexed VOICEVOX model metadata: %s", model_path)

        if not indexed_model_paths:
            raise VoicevoxConfigError(
                f"No VOICEVOX model metadata could be read from {settings.voicevox_model_path}",
            )
        LOGGER.info("Indexed %s VOICEVOX model(s)", len(indexed_model_paths))

        self._style_ids = frozenset(self._style_model_paths)
        LOGGER.info("Available VOICEVOX style IDs: %s", sorted(self._style_ids))

    def generate(self, text: str, speaker_id: int | None = None) -> bytes:
        style_id = speaker_id if speaker_id is not None else self.settings.speaker_id
        key = (text, style_id, int(self.settings.speed * 100))
        with self._lock:
            self._load_model_for_style(style_id)
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

    def _load_model_for_style(self, style_id: int) -> None:
        model_path = self._style_model_paths.get(style_id)
        if model_path is None:
            raise VoicevoxConfigError(f"VOICEVOX style ID is not available: {style_id}")
        if model_path in self._loaded_model_paths:
            return

        LOGGER.info("Opening VOICEVOX model for style_id=%s: %s", style_id, model_path)
        model = VoiceModelFile.open(model_path)
        LOGGER.info("Loading VOICEVOX model into synthesizer: %s", model_path)
        self._synthesizer.load_voice_model(model)
        self._loaded_model_paths.add(model_path)
        LOGGER.info("Loaded VOICEVOX model: %s", model_path)


def validate_environment(settings: Settings) -> None:
    """Validate that VOICEVOX files and ffmpeg are actually usable before startup."""
    LOGGER.info("Validating VOICEVOX environment")
    if not settings.voicevox_onnxruntime_path.is_file():
        raise VoicevoxConfigError(
            f"VOICEVOX_ONNXRUNTIME_PATH must be a file: {settings.voicevox_onnxruntime_path}",
        )
    if not settings.open_jtalk_dict_dir.is_dir():
        raise VoicevoxConfigError(
            f"OPEN_JTALK_DIC_DIR must be a directory: {settings.open_jtalk_dict_dir}",
        )
    model_paths = discover_voice_model_paths(
        settings.voicevox_model_path,
        settings.voicevox_model_exclude,
    )
    if not model_paths:
        raise VoicevoxConfigError(
            "VOICEVOX_MODEL_PATH must be a .vvm file or a directory containing .vvm files: "
            f"{settings.voicevox_model_path}",
        )
    LOGGER.info("VOICEVOX environment has %s model candidate(s)", len(model_paths))

    if shutil.which(settings.ffmpeg_path) is None:
        raise VoicevoxConfigError(
            f"ffmpeg executable not found: {settings.ffmpeg_path!r}. "
            "Install ffmpeg or set FFMPEG_PATH.",
        )
    LOGGER.info("VOICEVOX environment validation passed")


def validate_speaker_id(settings: Settings, synthesizer: SynthesizerLike) -> None:
    """Validate VOICEVOX_SPEAKER_ID against the styles available in the loaded model."""
    if not synthesizer.is_style_available(settings.speaker_id):
        raise VoicevoxConfigError(
            f"VOICEVOX_SPEAKER_ID={settings.speaker_id} is not available in the loaded "
            "VOICEVOX model. Check the available speaker/style IDs for your .vvm file.",
        )
