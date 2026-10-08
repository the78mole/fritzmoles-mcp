"""fritzmoles-mcp - MCP server for the telephony features of a FRITZ!Box."""

from .client import FritzTelephony
from .config import FritzConfig

__all__ = ["FritzConfig", "FritzTelephony"]
