from __future__ import annotations

from pathlib import Path

import pytest

from yomiage.config import ConfigError, Settings
from yomiage.voicevox import VoicevoxConfigError, validate_environment


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
        "VOICEVOX_CACHE_SIZE",
        "FFMPEG_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")


def test_valid_settings_use_defaults() -> None:
    settings = Settings.from_env()
    assert settings.max_tokens == 400
    assert settings.speaker_id == 3
    assert settings.speed == 1.2


def test_valid_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TOKENS", "123")
    monkeypatch.setenv("VOICEVOX_SPEAKER_ID", "8")
    monkeypatch.setenv("VOICEVOX_SPEED", "1.5")
    settings = Settings.from_env()
    assert settings.max_tokens == 123
    assert settings.speaker_id == 8
    assert settings.speed == 1.5


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
