"""Thin telephony-focused wrapper around fritzconnection / TR-064.

Everything the box answers as a URL (call list, voicemail list, call barring list, phonebooks)
is fetched through ``fetch`` and parsed with :mod:`fritzmoles_mcp.parsers`, so tests can inject
a fake transport instead of a live FRITZ!Box.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode, urlparse

from . import parsers
from .config import FritzConfig

ONTEL = "X_AVM-DE_OnTel1"
TAM = "X_AVM-DE_TAM1"
VOIP = "X_VoIP1"


class Connection(Protocol):
    """The subset of ``fritzconnection.FritzConnection`` used here."""

    def call_action(self, service_name: str, action_name: str, **kwargs: Any) -> dict[str, Any]: ...


Fetch = Callable[[str], bytes]


def _with_query(url: str, **params: Any) -> str:
    """Append non-empty query parameters to a URL that may already carry ``?sid=...``."""
    extra = {k: v for k, v in params.items() if v not in (None, "", 0)}
    if not extra:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{urlencode(extra)}"


class FritzTelephony:
    """Telephony operations of a FRITZ!Box: call lists, answering machines, barring, forwarding."""

    def __init__(self, connection: Connection, fetch: Fetch, *, base_url: str = "") -> None:
        self._fc = connection
        self._fetch = fetch
        self._base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------ construction

    @classmethod
    def connect(cls, config: FritzConfig) -> FritzTelephony:
        """Open a TR-064 connection using fritzconnection (network access happens here)."""
        from fritzconnection import FritzConnection

        config.validate()
        fc = FritzConnection(
            address=config.host,
            port=config.effective_port,
            user=config.username,
            password=config.password,
            use_tls=config.use_tls,
            timeout=config.timeout,
        )

        def fetch(url: str) -> bytes:
            response = fc.session.get(url, timeout=config.timeout)
            response.raise_for_status()
            return response.content

        return cls(fc, fetch, base_url=config.base_url)

    # ------------------------------------------------------------------ helpers

    def _action(self, service: str, action: str, **arguments: Any) -> dict[str, Any]:
        return self._fc.call_action(service, action, arguments=arguments)

    def _absolute(self, path_or_url: str) -> str:
        if urlparse(path_or_url).scheme:
            return path_or_url
        return f"{self._base_url}{path_or_url}"

    # ------------------------------------------------------------------ call list

    def get_calls(self, kind: str = "all", days: int | None = None, max_entries: int | None = None) -> dict[str, Any]:
        """Return recent calls, optionally filtered by kind (all/incoming/missed/outgoing/rejected/active)."""
        if kind not in parsers.CALL_TYPE_BY_NAME:
            raise ValueError(f"unknown call kind {kind!r}; use one of {sorted(parsers.CALL_TYPE_BY_NAME)}")
        url = self._action(ONTEL, "GetCallList")["NewCallListURL"]
        if not url:
            raise RuntimeError("The call list feature is disabled on this FRITZ!Box.")
        data = parsers.parse_call_list(self._fetch(_with_query(url, days=days, max=max_entries)))
        wanted = parsers.CALL_TYPE_BY_NAME[kind]
        if wanted:
            data["calls"] = [c for c in data["calls"] if c["type_id"] in wanted]
        data["kind"] = kind
        return data

    # ------------------------------------------------------------------ own numbers / dialing

    def get_own_numbers(self) -> list[dict[str, Any]]:
        """Return the phone numbers configured on the box (``X_VoIP:X_AVM-DE_GetNumbers``)."""
        xml = self._action(VOIP, "X_AVM-DE_GetNumbers")["NewNumberList"]
        return parsers.parse_number_list(xml)

    def dial(self, number: str) -> None:
        """Start a call via the box's dial helper (Wählhilfe must be enabled)."""
        number = number.strip()
        if not re.fullmatch(r"[+*#0-9]+", number):
            raise ValueError("number may only contain digits, +, * and #")
        self._action(VOIP, "X_AVM-DE_DialNumber", **{"NewX_AVM-DE_PhoneNumber": number})

    def hangup(self) -> None:
        """Abort a call started with :meth:`dial`."""
        self._action(VOIP, "X_AVM-DE_DialHangup")

    # ------------------------------------------------------------------ answering machines

    def list_answering_machines(self) -> dict[str, Any]:
        xml = self._action(TAM, "GetList")["NewTAMList"]
        return parsers.parse_tam_list(xml)

    def get_answering_machine(self, index: int) -> dict[str, Any]:
        info = self._action(TAM, "GetInfo", NewIndex=index)
        status = int(info.get("NewStatus") or 0)
        numbers = str(info.get("NewPhoneNumbers") or "").strip()
        return {
            "index": index,
            "name": info.get("NewName", ""),
            "enabled": bool(info.get("NewEnable")),
            "running": bool(info.get("NewTAMRunning")),
            "mode": info.get("NewMode", ""),
            "ring_seconds": info.get("NewRingSeconds"),
            "phone_numbers": [n.strip() for n in numbers.split(",") if n.strip()] if numbers else "all",
            "remaining_minutes": info.get("NewCapacity"),
            "busy": bool(status & 0b01),
            "no_space_left": bool(status & 0b10),
            "stick": info.get("NewStick"),
        }

    def set_answering_machine_enabled(self, index: int, enabled: bool) -> None:
        self._action(TAM, "SetEnable", NewIndex=index, NewEnable=enabled)

    def list_voicemails(self, index: int = 0, max_entries: int | None = None, only_new: bool = False) -> list[dict]:
        url = self._action(TAM, "GetMessageList", NewIndex=index)["NewURL"]
        messages = parsers.parse_tam_messages(self._fetch(_with_query(url, max=max_entries)))
        if only_new:
            messages = [m for m in messages if m["new"]]
        return messages

    def mark_voicemail(self, index: int, message_index: int, read: bool = True) -> None:
        self._action(TAM, "MarkMessage", NewIndex=index, NewMessageIndex=message_index, NewMarkedAsRead=read)

    def delete_voicemail(self, index: int, message_index: int) -> None:
        self._action(TAM, "DeleteMessage", NewIndex=index, NewMessageIndex=message_index)

    def download_voicemail(self, index: int, message_index: int, target_dir: Path) -> dict[str, Any]:
        """Download the recording of one voicemail message to ``target_dir`` and return its path."""
        message = next((m for m in self.list_voicemails(index) if m["index"] == message_index), None)
        if message is None:
            raise LookupError(f"answering machine {index} has no message with index {message_index}")
        path = message.get("recording_path")
        if not path:
            raise LookupError("this message has no recording path")
        url = self._absolute(path if "download.lua" in path else f"/download.lua?path={path}")
        data = self._fetch(url)
        target_dir = target_dir.expanduser()
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = (message.get("date") or "unknown").replace(":", "-")
        caller = re.sub(r"[^0-9+]", "", message.get("caller_number") or "") or "unknown"
        target = target_dir / f"tam{index}_msg{message_index}_{stamp}_{caller}.wav"
        target.write_bytes(data)
        return {"file": str(target), "bytes": len(data), "message": message}

    # ------------------------------------------------------------------ call barring (Rufsperren)

    def list_call_barrings(self) -> list[dict[str, Any]]:
        url = self._action(ONTEL, "GetCallBarringList")["NewPhonebookURL"]
        return parsers.parse_phonebook(self._fetch(url))["contacts"]

    def get_call_barring_by_number(self, number: str) -> dict[str, Any]:
        xml = self._action(ONTEL, "GetCallBarringEntryByNum", NewNumber=number.strip())["NewPhonebookEntryData"]
        return parsers.parse_contact_entry(xml)

    def add_call_barring(self, number: str, name: str = "") -> int:
        """Block an incoming number. Returns the new entry's unique id."""
        xml = parsers.build_contact_xml(number, name or f"Sperre {number.strip()}")
        result = self._action(ONTEL, "SetCallBarringEntry", NewPhonebookEntryData=xml)
        return int(result["NewPhonebookEntryUniqueID"])

    def remove_call_barring(self, uniqueid: int) -> None:
        self._action(ONTEL, "DeleteCallBarringEntryUID", NewPhonebookEntryUniqueID=uniqueid)

    def remove_call_barring_by_number(self, number: str) -> list[int]:
        """Remove every barring entry carrying ``number``; returns the removed unique ids."""
        wanted = _normalize_number(number)
        removed = []
        for entry in self.list_call_barrings():
            if (
                any(_normalize_number(n["number"]) == wanted for n in entry["numbers"])
                and entry["uniqueid"] is not None
            ):
                self.remove_call_barring(entry["uniqueid"])
                removed.append(entry["uniqueid"])
        return removed

    # ------------------------------------------------------------------ call forwarding (Rufumleitungen)

    def list_call_forwardings(self) -> list[dict[str, Any]]:
        xml = self._action(ONTEL, "GetDeflections")["NewDeflectionList"]
        return parsers.parse_deflections(xml)

    def get_call_forwarding(self, deflection_id: int) -> dict[str, Any]:
        info = self._action(ONTEL, "GetDeflection", NewDeflectionId=deflection_id)
        mode = str(info.get("NewMode", ""))
        type_ = str(info.get("NewType", ""))
        return {
            "id": deflection_id,
            "enabled": bool(info.get("NewEnable")),
            "type": type_,
            "type_description": parsers.DEFLECTION_TYPES.get(type_, type_),
            "number": info.get("NewNumber", ""),
            "forward_to": info.get("NewDeflectionToNumber", ""),
            "mode": mode,
            "mode_description": parsers.DEFLECTION_MODES.get(mode, mode),
            "outgoing": info.get("NewOutgoing", ""),
            "phonebook_id": info.get("NewPhonebookID"),
        }

    def set_call_forwarding_enabled(self, deflection_id: int, enabled: bool) -> None:
        self._action(ONTEL, "SetDeflectionEnable", NewDeflectionId=deflection_id, NewEnable=enabled)

    # ------------------------------------------------------------------ phonebooks

    def list_phonebooks(self) -> list[dict[str, Any]]:
        raw = str(self._action(ONTEL, "GetPhonebookList").get("NewPhonebookList") or "")
        ids = [int(x) for x in raw.split(",") if x.strip()]
        books = []
        for pid in ids:
            info = self._action(ONTEL, "GetPhonebook", NewPhonebookID=pid)
            books.append({"id": pid, "name": info.get("NewPhonebookName", ""), "url": info.get("NewPhonebookURL", "")})
        return books

    def get_phonebook(self, phonebook_id: int = 0) -> dict[str, Any]:
        info = self._action(ONTEL, "GetPhonebook", NewPhonebookID=phonebook_id)
        book = parsers.parse_phonebook(self._fetch(info["NewPhonebookURL"]))
        book["id"] = phonebook_id
        book["name"] = book["name"] or info.get("NewPhonebookName", "")
        return book

    def search_phonebook(self, query: str, phonebook_id: int = 0) -> list[dict[str, Any]]:
        """Case-insensitive search by name fragment or by number (digits compared without formatting)."""
        q = query.strip().lower()
        q_digits = _normalize_number(query)
        hits = []
        for contact in self.get_phonebook(phonebook_id)["contacts"]:
            if (
                q
                and q in contact["name"].lower()
                or q_digits
                and any(q_digits in _normalize_number(n["number"]) for n in contact["numbers"])
            ):
                hits.append(contact)
        return hits


def _normalize_number(number: str) -> str:
    return re.sub(r"[^0-9+*#]", "", number or "")
