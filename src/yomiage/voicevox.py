from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import Lock

from voicevox_core.blocking import Onnxruntime, OpenJtalk, Synthesizer, VoiceModelFile

from yomiage.config import Settings

CacheKey = tuple[str, int, int]


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


def validate_voicevox_paths(settings: Settings) -> None:
    paths: tuple[Path, ...] = (
        settings.voicevox_onnxruntime_path,
        settings.open_jtalk_dict_dir,
        settings.voicevox_model_path,
    )
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        joined = "\n".join(f"- {path}" for path in missing)
        raise RuntimeError(f"VOICEVOX files are missing:\n{joined}")
