from __future__ import annotations

import pytest

from wristscribe.__main__ import main
from wristscribe.config import ConfigError, load_config, write_initial_config


@pytest.fixture(autouse=True)
def no_key_env(monkeypatch):
    for var in ("WRISTSCRIBE_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_init_writes_a_valid_config(tmp_path):
    path = tmp_path / "config.toml"
    token = write_initial_config(path, api_key='gsk_abc"123')
    cfg = load_config(path)
    assert cfg.server.token == token
    assert len(token) >= 20
    assert cfg.transcription.resolved_api_key == 'gsk_abc"123'
    assert cfg.transcription.endpoint == "https://api.groq.com/openai/v1"
    assert cfg.transcription.model_name == "whisper-large-v3-turbo"
    assert "Simulink" in cfg.transcription.vocabulary
    assert cfg.output.mode == "paste"


def test_each_init_gets_a_new_token(tmp_path):
    assert write_initial_config(tmp_path / "a.toml") != write_initial_config(tmp_path / "b.toml")


def test_placeholder_token_is_refused(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[server]\ntoken = "CHANGE-ME"\n')
    with pytest.raises(ConfigError, match="init"):
        load_config(path)


def test_missing_file_points_to_init(tmp_path):
    with pytest.raises(ConfigError, match="init"):
        load_config(tmp_path / "nope.toml")


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ('[server]\ntoken = "short"', "at least"),
        ('[server]\ntoken = "long-enough-token"\nport = 70000', "port"),
        ('[server]\ntoken = "long-enough-token"\ncolour = "red"', "Unknown key"),
        ('[server]\ntoken = "long-enough-token"\n[transcription]\nprovider = "acme"', "provider"),
        ('[server]\ntoken = "long-enough-token"\n[transcription]\nprovider = "custom"', "base_url"),
        ('[server]\ntoken = "long-enough-token"\n[output]\nmode = "shout"', "mode"),
        ("[server\n", "not valid TOML"),
    ],
)
def test_invalid_configs(tmp_path, toml, message):
    path = tmp_path / "config.toml"
    path.write_text(toml)
    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_api_key_precedence(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    write_initial_config(path)
    cfg = load_config(path).transcription
    assert cfg.resolved_api_key == ""
    monkeypatch.setenv("GROQ_API_KEY", "from-groq-env")
    assert cfg.resolved_api_key == "from-groq-env"
    cfg.api_key = "from-file"
    assert cfg.resolved_api_key == "from-file"
    monkeypatch.setenv("WRISTSCRIBE_API_KEY", "from-wristscribe-env")
    assert cfg.resolved_api_key == "from-wristscribe-env"


def test_cli_init_refuses_to_overwrite(tmp_path, capsys):
    path = tmp_path / "config.toml"
    assert main(["init", "-c", str(path)]) == 0
    assert main(["init", "-c", str(path)]) == 1
    assert "already exists" in capsys.readouterr().out


def test_cli_reports_config_problems(tmp_path, capsys):
    assert main(["run", "-c", str(tmp_path / "missing.toml")]) == 1
    assert "Config problem" in capsys.readouterr().out
