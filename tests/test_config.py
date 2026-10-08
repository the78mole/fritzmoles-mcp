import pytest

from fritzmoles_mcp.config import FritzConfig


def test_defaults_from_empty_env():
    cfg = FritzConfig.from_env({})
    assert cfg.host == "fritz.box"
    assert cfg.effective_port == 49000
    assert cfg.base_url == "http://fritz.box:49000"
    assert cfg.use_tls is False
    assert cfg.read_only is False
    assert cfg.timeout == 10.0
    with pytest.raises(ValueError, match="FRITZ_USERNAME, FRITZ_PASSWORD"):
        cfg.validate()


def test_full_env():
    cfg = FritzConfig.from_env(
        {
            "FRITZ_HOST": "192.168.178.1",
            "FRITZ_USERNAME": "u",
            "FRITZ_PASSWORD": "p",
            "FRITZ_TLS": "True",
            "FRITZ_TIMEOUT": "2.5",
            "FRITZ_READ_ONLY": "yes",
            "FRITZ_DOWNLOAD_DIR": "/tmp/vm",
        }
    )
    assert cfg.effective_port == 49443
    assert cfg.base_url == "https://192.168.178.1:49443"
    assert cfg.timeout == 2.5
    assert cfg.read_only is True
    assert str(cfg.download_dir) == "/tmp/vm"
    cfg.validate()


def test_explicit_port_wins_over_tls_default():
    cfg = FritzConfig.from_env({"FRITZ_TLS": "1", "FRITZ_PORT": "50000"})
    assert cfg.effective_port == 50000


def test_from_os_environ(monkeypatch):
    monkeypatch.setenv("FRITZ_HOST", "box.local")
    monkeypatch.setenv("FRITZ_USERNAME", "a")
    monkeypatch.setenv("FRITZ_PASSWORD", "b")
    cfg = FritzConfig.from_env(load_dotenv_file=False)
    assert cfg.host == "box.local"
    assert cfg.username == "a"
