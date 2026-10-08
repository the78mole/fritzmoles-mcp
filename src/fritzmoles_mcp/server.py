"""MCP server exposing the telephony features of a FRITZ!Box."""

from __future__ import annotations

import logging
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer

from .client import FritzTelephony
from .config import FritzConfig

log = logging.getLogger(__name__)

INSTRUCTIONS = """\
Telephony features of a FRITZ!Box via TR-064: call lists (incoming, missed, outgoing), answering
machines and their voicemails, call barring (blocked numbers), call forwarding rules and phonebook
lookups. Network administration is deliberately out of scope.

Credentials come from the environment (FRITZ_HOST, FRITZ_USERNAME, FRITZ_PASSWORD, ...) or a .env file.
Tools that change box state are hidden when FRITZ_READ_ONLY=true. Every tool returns a dict; on failure
it is {"error": "<message>"} instead of raising, so check for that key.

Limitations imposed by AVM's TR-064 API: call forwarding rules can be listed and switched on/off but not
created or deleted; use the FRITZ!Box web UI for that. Call barring entries can be created and removed.
"""

CallKind = Literal["all", "incoming", "missed", "outgoing", "rejected", "active"]

_config: FritzConfig | None = None
_client: FritzTelephony | None = None


def get_config() -> FritzConfig:
    global _config
    if _config is None:
        _config = FritzConfig.from_env()
    return _config


def get_client() -> FritzTelephony:
    """Connect lazily on first use so importing the module never touches the network."""
    global _client
    if _client is None:
        _client = FritzTelephony.connect(get_config())
    return _client


def reset_client() -> None:
    """Drop the cached connection/config (used by tests and after credential changes)."""
    global _client, _config
    _client = None
    _config = None


def _call(fn: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Run ``fn`` and turn any failure into an ``{"error": ...}`` payload."""
    try:
        result = fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - deliberately broad: every failure should reach the LLM as text
        log.debug("tool failed", exc_info=True)
        return {"error": f"{type(exc).__name__}: {exc}"}
    if isinstance(result, dict):
        return result
    return {"result": result}


# ---------------------------------------------------------------------- read-only tools


def get_call_list(kind: CallKind = "all", days: int | None = None, max_entries: int | None = 50) -> dict[str, Any]:
    """List recent calls from the FRITZ!Box call list.

    Args:
        kind: all | incoming | missed | outgoing | rejected (blocked by call barring) | active (ongoing).
        days: Only calls from the last N days (1 = today and yesterday). None = no limit.
        max_entries: Maximum number of calls to fetch before filtering by kind (None = all).

    Returns:
        Dict with ``calls`` (newest first), each with type, date (ISO), caller/called numbers, name,
        device, duration_minutes and flags is_fax / is_answering_machine, plus ``recording_path`` for
        calls that left a voicemail.
    """
    return _call(lambda: get_client().get_calls(kind=kind, days=days, max_entries=max_entries))


def get_own_numbers() -> dict[str, Any]:
    """List the phone numbers (MSNs / SIP accounts) configured on the FRITZ!Box."""
    return _call(lambda: get_client().get_own_numbers())


def list_answering_machines() -> dict[str, Any]:
    """List all answering machines (TAMs) with their enabled state and the global TAM status."""
    return _call(lambda: get_client().list_answering_machines())


def get_answering_machine(index: int = 0) -> dict[str, Any]:
    """Details of one answering machine: name, enabled, mode, ring delay, assigned numbers, remaining minutes."""
    return _call(lambda: get_client().get_answering_machine(index))


def list_voicemails(tam_index: int = 0, max_entries: int | None = 50, only_new: bool = False) -> dict[str, Any]:
    """List voicemail messages of one answering machine (newest first).

    Args:
        tam_index: Answering machine index (0-4), see list_answering_machines.
        max_entries: Maximum number of messages to fetch.
        only_new: Only return messages not yet marked as read.
    """
    return _call(lambda: get_client().list_voicemails(tam_index, max_entries=max_entries, only_new=only_new))


def list_call_barrings() -> dict[str, Any]:
    """List blocked numbers (Rufsperren) with their unique ids."""
    return _call(lambda: get_client().list_call_barrings())


def get_call_barring(number: str) -> dict[str, Any]:
    """Look up the call barring entry for a specific number (error 714 means: not blocked)."""
    return _call(lambda: get_client().get_call_barring_by_number(number))


def list_call_forwardings() -> dict[str, Any]:
    """List call forwarding rules (Rufumleitungen) with id, enabled, type, mode and target number."""
    return _call(lambda: get_client().list_call_forwardings())


def get_call_forwarding(deflection_id: int) -> dict[str, Any]:
    """Details of one call forwarding rule by its id (see list_call_forwardings)."""
    return _call(lambda: get_client().get_call_forwarding(deflection_id))


def list_phonebooks() -> dict[str, Any]:
    """List the phonebooks on the box (id + name)."""
    return _call(lambda: get_client().list_phonebooks())


def search_phonebook(query: str, phonebook_id: int = 0) -> dict[str, Any]:
    """Search a phonebook by name fragment or by number fragment (useful to resolve caller numbers)."""
    return _call(lambda: get_client().search_phonebook(query, phonebook_id))


# ---------------------------------------------------------------------- writing tools


def _ok(**extra: Any) -> dict[str, Any]:
    return {"status": "ok", **extra}


def set_answering_machine_enabled(index: int, enabled: bool) -> dict[str, Any]:
    """Switch an answering machine on or off."""

    def run() -> dict[str, Any]:
        get_client().set_answering_machine_enabled(index, enabled)
        return _ok(index=index, enabled=enabled)

    return _call(run)


def mark_voicemail(tam_index: int, message_index: int, read: bool = True) -> dict[str, Any]:
    """Mark a voicemail message as read (default) or unread."""

    def run() -> dict[str, Any]:
        get_client().mark_voicemail(tam_index, message_index, read)
        return _ok(tam_index=tam_index, message_index=message_index, read=read)

    return _call(run)


def delete_voicemail(tam_index: int, message_index: int) -> dict[str, Any]:
    """Permanently delete a voicemail message."""

    def run() -> dict[str, Any]:
        get_client().delete_voicemail(tam_index, message_index)
        return _ok(tam_index=tam_index, message_index=message_index, deleted=True)

    return _call(run)


def download_voicemail(tam_index: int, message_index: int, target_dir: str | None = None) -> dict[str, Any]:
    """Download the audio recording of a voicemail to a local file (default dir: FRITZ_DOWNLOAD_DIR)."""
    from pathlib import Path

    directory = Path(target_dir) if target_dir else get_config().download_dir
    return _call(lambda: get_client().download_voicemail(tam_index, message_index, directory))


def add_call_barring(number: str, name: str = "") -> dict[str, Any]:
    """Block an incoming number (Rufsperre). Returns the unique id of the new entry."""

    def run() -> dict[str, Any]:
        uid = get_client().add_call_barring(number, name)
        return _ok(uniqueid=uid, number=number, name=name)

    return _call(run)


def remove_call_barring(uniqueid: int | None = None, number: str | None = None) -> dict[str, Any]:
    """Unblock a number, either by the entry's unique id or by the number itself."""

    def run() -> dict[str, Any]:
        client = get_client()
        if uniqueid is not None:
            client.remove_call_barring(uniqueid)
            return _ok(removed=[uniqueid])
        if number:
            removed = client.remove_call_barring_by_number(number)
            if not removed:
                return {"error": f"no call barring entry found for {number!r}"}
            return _ok(removed=removed)
        return {"error": "pass either uniqueid or number"}

    return _call(run)


def set_call_forwarding_enabled(deflection_id: int, enabled: bool) -> dict[str, Any]:
    """Enable or disable an existing call forwarding rule (Rufumleitung)."""

    def run() -> dict[str, Any]:
        get_client().set_call_forwarding_enabled(deflection_id, enabled)
        return _ok(deflection_id=deflection_id, enabled=enabled)

    return _call(run)


def dial_number(number: str) -> dict[str, Any]:
    """Start a call via the box's dial helper: your phone rings first, then the number is dialed."""

    def run() -> dict[str, Any]:
        get_client().dial(number)
        return _ok(number=number)

    return _call(run)


def hangup() -> dict[str, Any]:
    """Abort a call started with dial_number."""

    def run() -> dict[str, Any]:
        get_client().hangup()
        return _ok()

    return _call(run)


READ_TOOLS = (
    get_call_list,
    get_own_numbers,
    list_answering_machines,
    get_answering_machine,
    list_voicemails,
    list_call_barrings,
    get_call_barring,
    list_call_forwardings,
    get_call_forwarding,
    list_phonebooks,
    search_phonebook,
)

WRITE_TOOLS = (
    set_answering_machine_enabled,
    mark_voicemail,
    delete_voicemail,
    download_voicemail,
    add_call_barring,
    remove_call_barring,
    set_call_forwarding_enabled,
    dial_number,
    hangup,
)


def create_server(read_only: bool = False) -> MCPServer:
    """Build an MCPServer with all read tools and, unless ``read_only``, the writing tools too."""
    server = MCPServer("fritzmoles-mcp", instructions=INSTRUCTIONS)
    for fn in READ_TOOLS:
        server.add_tool(fn)
    if not read_only:
        for fn in WRITE_TOOLS:
            server.add_tool(fn)
    return server


mcp = create_server(read_only=get_config().read_only)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    mcp.run()


if __name__ == "__main__":
    main()
