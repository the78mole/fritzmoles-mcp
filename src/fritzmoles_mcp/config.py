"""Configuration from environment variables / a local ``.env`` file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_HOST = "fritz.box"
DEFAULT_PORT = 49000
DEFAULT_TLS_PORT = 49443
DEFAULT_TIMEOUT = 10.0

_TRUE = {"1", "true", "yes", "on"}


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in _TRUE


@dataclass(frozen=True)
class FritzConfig:
    """Connection settings for the FRITZ!Box TR-064 interface."""

    host: str = DEFAULT_HOST
    port: int | None = None
    username: str | None = None
    password: str | None = None
    use_tls: bool = False
    timeout: float = DEFAULT_TIMEOUT
    read_only: bool = False
    download_dir: Path = Path("~/fritz-voicemails")

    @property
    def effective_port(self) -> int:
        if self.port is not None:
            return self.port
        return DEFAULT_TLS_PORT if self.use_tls else DEFAULT_PORT

    @property
    def base_url(self) -> str:
        scheme = "https" if self.use_tls else "http"
        return f"{scheme}://{self.host}:{self.effective_port}"

    def validate(self) -> None:
        """Raise ``ValueError`` when the credentials needed for TR-064 are missing."""
        missing = [
            name for name, value in (("FRITZ_USERNAME", self.username), ("FRITZ_PASSWORD", self.password)) if not value
        ]
        if missing:
            raise ValueError(f"Missing FRITZ!Box credentials: set {', '.join(missing)} (environment or .env file).")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None, *, load_dotenv_file: bool = True) -> FritzConfig:
        """Build the config from ``env`` (default: ``os.environ``), optionally loading ``.env`` first.

        ``load_dotenv`` never overrides variables that are already set, so values from the
        MCP host configuration always win over a ``.env`` file in the working directory.
        """
        if env is None:
            if load_dotenv_file:
                load_dotenv()
            env = dict(os.environ)

        port_raw = env.get("FRITZ_PORT", "").strip()
        timeout_raw = env.get("FRITZ_TIMEOUT", "").strip()
        download_dir = env.get("FRITZ_DOWNLOAD_DIR", "").strip() or "~/fritz-voicemails"

        return cls(
            host=env.get("FRITZ_HOST", "").strip() or DEFAULT_HOST,
            port=int(port_raw) if port_raw else None,
            username=env.get("FRITZ_USERNAME") or None,
            password=env.get("FRITZ_PASSWORD") or None,
            use_tls=_as_bool(env.get("FRITZ_TLS")),
            timeout=float(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT,
            read_only=_as_bool(env.get("FRITZ_READ_ONLY")),
            download_dir=Path(download_dir),
        )
