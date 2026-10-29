from __future__ import annotations

import logging
import shutil
import wave
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from threading import Lock
from types import TracebackType
from typing import Protocol, Self, runtime_checkable

from voicevox_core.blocking import (
    Onnxruntime,
    OpenJtalk,
    SynthesisStream,
    Synthesizer,
    VoiceModelFile,
)

from yomiage.config import Settings

CacheKey = tuple[str, int, int]
VOICE_MODEL_GLOB = "*.vvm"
# StyleMeta.type of styles in new-format (vvm_format_version=2) VVMs that support
# Synthesizer.streaming_synthesis. They also support regular synthesis.
STREAMING_STYLE_TYPE = "streaming_talk"
LOGGER = logging.getLogger(__name__)


class VoicevoxConfigError(RuntimeError):
    """Raised when the VOICEVOX runtime environment is misconfigured."""


class StreamingNotSupportedError(RuntimeError):
    """Raised when streaming is requested for a style without ``streaming_talk`` support."""


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


@dataclass(frozen=True)
class PcmFormat:
    """Format of the raw ``s16le`` PCM yielded by a :class:`PcmStream`."""

    sample_rate: int
    channels: int


class PcmStream(Protocol):
    """Iterator of PCM segments. Must be iterated and closed on a single thread."""

    @property
    def format(self) -> PcmFormat: ...

    def __iter__(self) -> Iterator[bytes]: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


@runtime_checkable
class StreamingSynthesizerLike(SynthesizerLike, Protocol):
    """Optional extension used by the ``streaming``/``auto`` synthesis modes."""

    def get_cached(self, text: str, speaker_id: int | None = None) -> bytes | None: ...

    def supports_streaming(self, style_id: int) -> bool: ...

    def streaming_style_ids(self) -> frozenset[int]: ...

    def open_stream(self, text: str, speaker_id: int | None = None) -> PcmStream: ...


def parse_wav_header(header: bytes) -> PcmFormat:
    """Read sample rate and channel count from the 44-byte header ``streaming_synthesis`` yields."""
    with BytesIO(header) as buffer, wave.open(buffer, "rb") as wav:
        if wav.getsampwidth() != 2:  # noqa: PLR2004 - s16le
            raise ValueError(f"Unsupported sample width: {wav.getsampwidth()}")
        return PcmFormat(sample_rate=wav.getframerate(), channels=wav.getnchannels())


def expected_wav_data_size(header: bytes) -> int:
    with BytesIO(header) as buffer, wave.open(buffer, "rb") as wav:
        return wav.getnframes() * wav.getnchannels() * wav.getsampwidth()


class VoicevoxPcmStream:
    """Wraps :class:`SynthesisStream`, serialising each segment under the synthesizer lock.

    The lock is taken per segment rather than for the whole utterance so one guild's
    slow playback (backpressure) never blocks synthesis for other guilds. The
    complete WAV is cached only if every segment was produced.
    """

    def __init__(
        self,
        owner: VoicevoxSynthesizer,
        stream: SynthesisStream,
        header: bytes,
        key: CacheKey,
    ) -> None:
        self._owner = owner
        self._stream: SynthesisStream | None = stream
        self._header = header
        self._key = key
        self._format = parse_wav_header(header)
        self._expected_size = expected_wav_data_size(header)
        self._pcm: bytearray | None = bytearray() if owner.settings.cache_size > 0 else None

    @property
    def format(self) -> PcmFormat:
        return self._format

    def __iter__(self) -> Iterator[bytes]:
        return self

    def __next__(self) -> bytes:
        stream = self._stream
        if stream is None:
            raise StopIteration
        with self._owner.lock:
            try:
                pcm = next(stream)
            except StopIteration:
                self._complete_locked()
                raise
        if self._pcm is not None:
            self._pcm += pcm
        return pcm

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        stream = self._stream
        self._stream = None
        self._pcm = None
        if stream is not None:
            with self._owner.lock:
                stream.clear()

    def _complete_locked(self) -> None:
        pcm = self._pcm
        self._stream = None
        self._pcm = None
        if pcm is None:
            return
        if len(pcm) != self._expected_size:
            LOGGER.warning(
                "Streaming synthesis produced %s bytes, expected %s; not caching",
                len(pcm),
                self._expected_size,
            )
            return
        self._owner.store_cache_locked(self._key, self._header + bytes(pcm))


class VoicevoxSynthesizer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cache: OrderedDict[CacheKey, bytes] = OrderedDict()
        self._lock = Lock()
        self._style_model_paths: dict[int, Path] = {}
        self._streaming_style_ids: set[int] = set()
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
                        if style.type == STREAMING_STYLE_TYPE:
                            self._streaming_style_ids.add(int(style.id))
                        else:
                            self._streaming_style_ids.discard(int(style.id))
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
        self._streaming_style_id_set = frozenset(self._streaming_style_ids)
        LOGGER.info("Available VOICEVOX style IDs: %s", sorted(self._style_ids))
        LOGGER.info(
            "Streaming-capable VOICEVOX style IDs (%s): %s",
            STREAMING_STYLE_TYPE,
            sorted(self._streaming_style_id_set),
        )

    @property
    def lock(self) -> Lock:
        """Serialises every call into the native synthesizer and the cache."""
        return self._lock

    def generate(self, text: str, speaker_id: int | None = None) -> bytes:
        style_id = self._resolve_style(speaker_id)
        key = self._cache_key(text, style_id)
        with self._lock:
            self._load_model_for_style(style_id)
            cached = self._get_cached_locked(key)
            if cached is not None:
                return cached

            audio_query = self._synthesizer.create_audio_query(text, style_id)
            audio_query.speed_scale = self.settings.speed
            wav_data = self._synthesizer.synthesis(audio_query, style_id)

            self.store_cache_locked(key, wav_data)
            return wav_data

    def get_cached(self, text: str, speaker_id: int | None = None) -> bytes | None:
        key = self._cache_key(text, self._resolve_style(speaker_id))
        with self._lock:
            return self._get_cached_locked(key)

    def supports_streaming(self, style_id: int) -> bool:
        return style_id in self._streaming_style_id_set

    def streaming_style_ids(self) -> frozenset[int]:
        return self._streaming_style_id_set

    def open_stream(self, text: str, speaker_id: int | None = None) -> VoicevoxPcmStream:
        """Start streaming synthesis. The first PCM segment is produced lazily on iteration."""
        style_id = self._resolve_style(speaker_id)
        if not self.supports_streaming(style_id):
            raise StreamingNotSupportedError(
                f"VOICEVOX style ID {style_id} is not a {STREAMING_STYLE_TYPE!r} style",
            )
        key = self._cache_key(text, style_id)
        with self._lock:
            self._load_model_for_style(style_id)
            audio_query = self._synthesizer.create_audio_query(text, style_id)
            audio_query.speed_scale = self.settings.speed
            stream = self._synthesizer.streaming_synthesis(
                audio_query,
                style_id,
                segment_length=self.settings.stream_segment_seconds,
            )
            # The first element is always the 44-byte WAV header and never raises.
            header = next(stream)
        try:
            return VoicevoxPcmStream(self, stream, header, key)
        except Exception:
            with self._lock:
                stream.clear()
            raise

    def is_style_available(self, style_id: int) -> bool:
        return style_id in self._style_ids

    def available_style_ids(self) -> frozenset[int]:
        return self._style_ids

    def store_cache_locked(self, key: CacheKey, wav_data: bytes) -> None:
        if self.settings.cache_size <= 0:
            return
        self._cache[key] = wav_data
        self._cache.move_to_end(key)
        while len(self._cache) > self.settings.cache_size:
            self._cache.popitem(last=False)

    def _resolve_style(self, speaker_id: int | None) -> int:
        return speaker_id if speaker_id is not None else self.settings.speaker_id

    def _cache_key(self, text: str, style_id: int) -> CacheKey:
        return (text, style_id, int(self.settings.speed * 100))

    def _get_cached_locked(self, key: CacheKey) -> bytes | None:
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
        return cached

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


def validate_synthesis_mode(settings: Settings, synthesizer: SynthesizerLike) -> None:
    """Fail fast when ``streaming`` mode cannot stream the default speaker."""
    mode = settings.synthesis_mode
    if mode == "normal":
        return
    streaming_ids = (
        synthesizer.streaming_style_ids()
        if isinstance(synthesizer, StreamingSynthesizerLike)
        else frozenset[int]()
    )
    if mode == "streaming" and settings.speaker_id not in streaming_ids:
        raise VoicevoxConfigError(
            f"VOICEVOX_SYNTHESIS_MODE=streaming requires VOICEVOX_SPEAKER_ID={settings.speaker_id} "
            f"to be a {STREAMING_STYLE_TYPE!r} style from a new-format VVM "
            "(vvm_format_version=2). Install streaming-capable VVMs, choose another speaker, "
            "or use VOICEVOX_SYNTHESIS_MODE=auto / normal.",
        )
    if not streaming_ids:
        LOGGER.warning(
            "VOICEVOX_SYNTHESIS_MODE=auto but no loaded VVM has %r styles; "
            "every message will use normal synthesis",
            STREAMING_STYLE_TYPE,
        )
