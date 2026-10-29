from __future__ import annotations

from pathlib import Path

import pytest

from yomiage.config import ConfigError, Settings
from yomiage.voicevox import (
    VoicevoxConfigError,
    discover_voice_model_paths,
    validate_environment,
)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "DISCORD_BOT_TOKEN",
        "BOT_ID",
        "YOMIAGE_DB",
        "MAX_TOKENS",
        "VOICEVOX_SPEAKER_ID",
        "VOICEVOX_SPEED",
        "VOICEVOX_ONNXRUNTIME_PATH",
        "OPEN_JTALK_DIC_DIR",
        "VOICEVOX_MODEL_PATH",
        "VOICEVOX_MODEL_EXCLUDE",
        "VOICEVOX_ACCELERATION_MODE",
        "VOICEVOX_CACHE_SIZE",
        "FFMPEG_PATH",
        "VOICEVOX_SYNTHESIS_MODE",
        "VOICEVOX_STREAM_SEGMENT_SECONDS",
        "VOICEVOX_STREAM_BUFFER_SECONDS",
        "VOICEVOX_PERFORMANCE_LOG",
        "VOICEVOX_CPU_NUM_THREADS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")


def test_valid_settings_use_defaults() -> None:
    settings = Settings.from_env()
    assert settings.max_tokens == 400
    assert settings.speaker_id == 3
    assert settings.speed == 1.2
    assert settings.voicevox_model_exclude == ()
    assert settings.voicevox_acceleration_mode == "CPU"


def test_valid_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TOKENS", "123")
    monkeypatch.setenv("VOICEVOX_SPEAKER_ID", "8")
    monkeypatch.setenv("VOICEVOX_SPEED", "1.5")
    monkeypatch.setenv("VOICEVOX_MODEL_EXCLUDE", "4.vvm, 9")
    monkeypatch.setenv("VOICEVOX_ACCELERATION_MODE", "auto")
    settings = Settings.from_env()
    assert settings.max_tokens == 123
    assert settings.speaker_id == 8
    assert settings.speed == 1.5
    assert settings.voicevox_model_exclude == ("4.vvm", "9")
    assert settings.voicevox_acceleration_mode == "AUTO"


def test_missing_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="DISCORD_BOT_TOKEN"):
        Settings.from_env()


def test_invalid_int_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TOKENS", "abc")
    with pytest.raises(ConfigError, match="MAX_TOKENS"):
        Settings.from_env()


def test_invalid_float_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICEVOX_SPEED", "fast")
    with pytest.raises(ConfigError, match="VOICEVOX_SPEED"):
        Settings.from_env()


def test_invalid_voicevox_acceleration_mode_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICEVOX_ACCELERATION_MODE", "cuda")
    with pytest.raises(ConfigError, match="VOICEVOX_ACCELERATION_MODE"):
        Settings.from_env()


def test_negative_max_tokens_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TOKENS", "-1")
    with pytest.raises(ConfigError, match="MAX_TOKENS"):
        Settings.from_env()


def test_zero_max_tokens_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TOKENS", "0")
    with pytest.raises(ConfigError, match="MAX_TOKENS"):
        Settings.from_env()


def test_zero_cache_size_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICEVOX_CACHE_SIZE", "0")
    settings = Settings.from_env()
    assert settings.cache_size == 0


def test_negative_cache_size_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICEVOX_CACHE_SIZE", "-1")
    with pytest.raises(ConfigError, match="VOICEVOX_CACHE_SIZE"):
        Settings.from_env()


def test_zero_speed_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICEVOX_SPEED", "0")
    with pytest.raises(ConfigError, match="VOICEVOX_SPEED"):
        Settings.from_env()


def test_negative_speaker_id_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICEVOX_SPEAKER_ID", "-1")
    with pytest.raises(ConfigError, match="VOICEVOX_SPEAKER_ID"):
        Settings.from_env()


def test_negative_bot_id_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_ID", "-1")
    with pytest.raises(ConfigError, match="BOT_ID"):
        Settings.from_env()


def test_nonexistent_voicevox_path_fails_environment_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    onnxruntime_path = tmp_path / "onnxruntime.so"
    dict_path = tmp_path / "dict"
    onnxruntime_path.write_bytes(b"onnxruntime")
    dict_path.mkdir()

    monkeypatch.setenv("VOICEVOX_ONNXRUNTIME_PATH", str(onnxruntime_path))
    monkeypatch.setenv("OPEN_JTALK_DIC_DIR", str(dict_path))
    monkeypatch.setenv("VOICEVOX_MODEL_PATH", "/nonexistent/path/model.vvm")
    settings = Settings.from_env()
    with pytest.raises(VoicevoxConfigError, match="VOICEVOX_MODEL_PATH"):
        validate_environment(settings)


def test_voicevox_path_types_are_validated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    onnxruntime_path = tmp_path / "onnxruntime"
    dict_path = tmp_path / "dict"
    model_path = tmp_path / "model.vvm"
    dict_path.mkdir()
    model_path.write_bytes(b"model")

    monkeypatch.setenv("VOICEVOX_ONNXRUNTIME_PATH", str(onnxruntime_path))
    monkeypatch.setenv("OPEN_JTALK_DIC_DIR", str(dict_path))
    monkeypatch.setenv("VOICEVOX_MODEL_PATH", str(model_path))

    with pytest.raises(VoicevoxConfigError, match="VOICEVOX_ONNXRUNTIME_PATH"):
        validate_environment(Settings.from_env())


def test_environment_validation_accepts_existing_files_and_ffmpeg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    onnxruntime_path = tmp_path / "onnxruntime.so"
    dict_path = tmp_path / "dict"
    model_path = tmp_path / "model.vvm"
    onnxruntime_path.write_bytes(b"onnxruntime")
    dict_path.mkdir()
    model_path.write_bytes(b"model")

    monkeypatch.setenv("VOICEVOX_ONNXRUNTIME_PATH", str(onnxruntime_path))
    monkeypatch.setenv("OPEN_JTALK_DIC_DIR", str(dict_path))
    monkeypatch.setenv("VOICEVOX_MODEL_PATH", str(model_path))
    monkeypatch.setenv("FFMPEG_PATH", "python3")

    validate_environment(Settings.from_env())


def test_voicevox_model_path_discovers_sibling_vvm_files(tmp_path: Path) -> None:
    models_dir = tmp_path / "vvms"
    models_dir.mkdir()
    model_0 = models_dir / "0.vvm"
    model_1 = models_dir / "1.vvm"
    model_10 = models_dir / "10.vvm"
    ignored = models_dir / "README.txt"
    model_10.write_bytes(b"model10")
    model_1.write_bytes(b"model1")
    ignored.write_text("ignored", encoding="utf-8")
    model_0.write_bytes(b"model0")

    assert discover_voice_model_paths(model_0) == (model_0, model_1, model_10)


def test_voicevox_model_path_excludes_matching_models(tmp_path: Path) -> None:
    models_dir = tmp_path / "vvms"
    models_dir.mkdir()
    model_0 = models_dir / "0.vvm"
    model_4 = models_dir / "4.vvm"
    model_9 = models_dir / "9.vvm"
    model_0.write_bytes(b"model0")
    model_4.write_bytes(b"model4")
    model_9.write_bytes(b"model9")

    assert discover_voice_model_paths(models_dir, excludes=("4.vvm", "9")) == (model_0,)


def test_voicevox_model_path_can_be_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    onnxruntime_path = tmp_path / "onnxruntime.so"
    dict_path = tmp_path / "dict"
    models_dir = tmp_path / "vvms"
    onnxruntime_path.write_bytes(b"onnxruntime")
    dict_path.mkdir()
    models_dir.mkdir()
    (models_dir / "0.vvm").write_bytes(b"model")

    monkeypatch.setenv("VOICEVOX_ONNXRUNTIME_PATH", str(onnxruntime_path))
    monkeypatch.setenv("OPEN_JTALK_DIC_DIR", str(dict_path))
    monkeypatch.setenv("VOICEVOX_MODEL_PATH", str(models_dir))
    monkeypatch.setenv("FFMPEG_PATH", "python3")

    validate_environment(Settings.from_env())


def test_synthesis_settings_defaults() -> None:
    settings = Settings.from_env()
    assert settings.synthesis_mode == "normal"
    assert settings.stream_segment_seconds == 0.3
    assert settings.stream_buffer_seconds == 0.5
    assert settings.performance_log is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("normal", "normal"), ("STREAMING", "streaming"), (" Auto ", "auto")],
)
def test_synthesis_mode_is_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    expected: str,
) -> None:
    monkeypatch.setenv("VOICEVOX_SYNTHESIS_MODE", raw)
    assert Settings.from_env().synthesis_mode == expected


def test_invalid_synthesis_mode_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICEVOX_SYNTHESIS_MODE", "stream")
    with pytest.raises(ConfigError, match="VOICEVOX_SYNTHESIS_MODE must be one of"):
        Settings.from_env()


def test_streaming_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICEVOX_STREAM_SEGMENT_SECONDS", "0.2")
    monkeypatch.setenv("VOICEVOX_STREAM_BUFFER_SECONDS", "0")
    monkeypatch.setenv("VOICEVOX_PERFORMANCE_LOG", "TRUE")
    settings = Settings.from_env()
    assert settings.stream_segment_seconds == 0.2
    assert settings.stream_buffer_seconds == 0.0
    assert settings.performance_log is True


@pytest.mark.parametrize("raw", ["0", "-0.1", "0.005", "11", "fast"])
def test_invalid_stream_segment_seconds_raises(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("VOICEVOX_STREAM_SEGMENT_SECONDS", raw)
    with pytest.raises(ConfigError, match="VOICEVOX_STREAM_SEGMENT_SECONDS"):
        Settings.from_env()


@pytest.mark.parametrize("raw", ["-0.1", "11", "lots"])
def test_invalid_stream_buffer_seconds_raises(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("VOICEVOX_STREAM_BUFFER_SECONDS", raw)
    with pytest.raises(ConfigError, match="VOICEVOX_STREAM_BUFFER_SECONDS"):
        Settings.from_env()


@pytest.mark.parametrize(("raw", "expected"), [("1", True), ("on", True), ("No", False)])
def test_performance_log_accepts_boolean_words(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    expected: bool,
) -> None:
    monkeypatch.setenv("VOICEVOX_PERFORMANCE_LOG", raw)
    assert Settings.from_env().performance_log is expected


def test_cpu_num_threads_defaults_to_four() -> None:
    assert Settings.from_env().cpu_num_threads == 4


@pytest.mark.parametrize(("raw", "expected"), [("0", 0), ("12", 12)])
def test_cpu_num_threads_from_env(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    expected: int,
) -> None:
    monkeypatch.setenv("VOICEVOX_CPU_NUM_THREADS", raw)
    assert Settings.from_env().cpu_num_threads == expected


@pytest.mark.parametrize("raw", ["-1", "1025", "many"])
def test_invalid_cpu_num_threads_raises(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("VOICEVOX_CPU_NUM_THREADS", raw)
    with pytest.raises(ConfigError, match="VOICEVOX_CPU_NUM_THREADS"):
        Settings.from_env()


def test_invalid_performance_log_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICEVOX_PERFORMANCE_LOG", "maybe")
    with pytest.raises(ConfigError, match="VOICEVOX_PERFORMANCE_LOG"):
        Settings.from_env()
