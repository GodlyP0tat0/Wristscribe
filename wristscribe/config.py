"""Load and validate WristScribe's TOML configuration."""

from __future__ import annotations

import json
import os
import secrets
import tomllib
from dataclasses import dataclass, field, fields
from importlib import resources
from pathlib import Path

PLACEHOLDER_TOKEN = "CHANGE-ME"
OUTPUT_MODES = ("paste", "type", "print")
MIN_TOKEN_LENGTH = 12


@dataclass(frozen=True)
class Provider:
    base_url: str
    default_model: str
    key_env: str


PROVIDERS: dict[str, Provider] = {
    "groq": Provider("https://api.groq.com/openai/v1", "whisper-large-v3-turbo", "GROQ_API_KEY"),
    "openai": Provider("https://api.openai.com/v1", "gpt-4o-mini-transcribe", "OPENAI_API_KEY"),
}


class ConfigError(Exception):
    """The config file is missing or invalid. The message is shown to the user as-is."""


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8765
    token: str = ""


@dataclass
class TranscriptionConfig:
    provider: str = "groq"
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    language: str = "en"
    vocabulary: list[str] = field(default_factory=list)
    timeout_seconds: float = 60.0

    @property
    def endpoint(self) -> str:
        if self.base_url:
            return self.base_url.rstrip("/")
        return PROVIDERS[self.provider].base_url

    @property
    def model_name(self) -> str:
        return self.model or PROVIDERS[self.provider].default_model

    @property
    def resolved_api_key(self) -> str:
        """Env var WRISTSCRIBE_API_KEY > config file > provider's usual env var."""
        key = os.environ.get("WRISTSCRIBE_API_KEY") or self.api_key
        if not key and self.provider in PROVIDERS:
            key = os.environ.get(PROVIDERS[self.provider].key_env, "")
        return key.strip()


@dataclass
class OutputConfig:
    mode: str = "paste"
    restore_clipboard: bool = True
    append_space: bool = True


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    transcription: TranscriptionConfig = field(default_factory=TranscriptionConfig)
    output: OutputConfig = field(default_factory=OutputConfig)


def _section(data: dict, name: str, cls):
    raw = data.get(name, {})
    if not isinstance(raw, dict):
        raise ConfigError(f"[{name}] must be a table")
    unknown = set(raw) - {f.name for f in fields(cls)}
    if unknown:
        raise ConfigError(f"Unknown key(s) in [{name}]: {', '.join(sorted(unknown))}")
    return cls(**raw)


def validate(cfg: Config) -> None:
    s, t, o = cfg.server, cfg.transcription, cfg.output
    if not isinstance(s.port, int) or not 1 <= s.port <= 65535:
        raise ConfigError("[server] port must be a number between 1 and 65535")
    if not s.token or s.token == PLACEHOLDER_TOKEN:
        raise ConfigError("[server] token is not set. Run `python -m wristscribe init` to create one.")
    if len(s.token) < MIN_TOKEN_LENGTH:
        raise ConfigError(f"[server] token must be at least {MIN_TOKEN_LENGTH} characters")
    if t.provider not in (*PROVIDERS, "custom"):
        raise ConfigError(f'[transcription] provider must be one of: {", ".join([*PROVIDERS, "custom"])}')
    if t.provider == "custom" and not (t.base_url and t.model):
        raise ConfigError('[transcription] provider "custom" needs both base_url and model')
    if not isinstance(t.vocabulary, list) or not all(isinstance(w, str) for w in t.vocabulary):
        raise ConfigError("[transcription] vocabulary must be a list of strings")
    if o.mode not in OUTPUT_MODES:
        raise ConfigError(f'[output] mode must be one of: {", ".join(OUTPUT_MODES)}')


def load_config(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"No config file at {path}. Run `python -m wristscribe init` first.")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc
    try:
        cfg = Config(
            server=_section(data, "server", ServerConfig),
            transcription=_section(data, "transcription", TranscriptionConfig),
            output=_section(data, "output", OutputConfig),
        )
    except TypeError as exc:
        raise ConfigError(f"Invalid config: {exc}") from exc
    validate(cfg)
    return cfg


def template_text() -> str:
    return resources.files("wristscribe").joinpath("config_template.toml").read_text(encoding="utf-8")


def write_initial_config(path: str | Path, api_key: str = "") -> str:
    """Write a fresh config with a random token. Returns the token."""
    token = secrets.token_urlsafe(18)
    text = template_text().replace(f'token = "{PLACEHOLDER_TOKEN}"', f'token = "{token}"', 1)
    if api_key:
        # A JSON string literal is also a valid TOML basic string.
        text = text.replace('api_key = ""', f"api_key = {json.dumps(api_key)}", 1)
    Path(path).write_text(text, encoding="utf-8")
    return token
