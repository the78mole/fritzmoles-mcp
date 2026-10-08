"""Parsers for the XML documents the FRITZ!Box serves next to its TR-064 SOAP actions.

All functions are pure (bytes/str in, plain dicts out) so they can be unit-tested against
the examples from the AVM specifications without a box.
"""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from typing import Any

CALL_TYPES: dict[int, str] = {
    1: "incoming",
    2: "missed",
    3: "outgoing",
    9: "active_incoming",
    10: "rejected",
    11: "active_outgoing",
}

CALL_TYPE_BY_NAME: dict[str, list[int]] = {
    "all": [],
    "incoming": [1, 9],
    "missed": [2],
    "outgoing": [3, 11],
    "rejected": [10],
    "active": [9, 11],
}

DEFLECTION_MODES: dict[str, str] = {
    "eImmediately": "immediately",
    "eShortDelayed": "short delay",
    "eLongDelayed": "long delay",
    "eDelayed": "delayed",
    "eBusy": "when busy",
    "eDelayedOrBusy": "delayed or busy",
    "eParallelCall": "parallel call",
    "eNoSignal": "do not signal",
    "eVIP": "VIP",
    "eBellBlockade": "bell blockade",
    "eDirectCall": "direct call",
    "eOff": "off",
    "eUnknown": "unknown",
}

DEFLECTION_TYPES: dict[str, str] = {
    "fromAll": "all callers",
    "fromNumber": "specific number",
    "fromAnonymous": "anonymous callers",
    "fromPB": "callers in phonebook",
    "fromNotInPhonebook": "callers not in phonebook",
    "fromVIP": "VIP callers",
    "toAny": "any own number",
    "toMSN": "a specific own number",
    "toPOTS": "analog line",
    "toVoIP": "VoIP line",
    "fon1": "phone port 1",
    "fon2": "phone port 2",
    "fon3": "phone port 3",
    "fon4": "phone port 4",
    "unknown": "unknown",
}


def _text(node: ET.Element | None, name: str) -> str:
    if node is None:
        return ""
    child = node.find(name)
    return (child.text or "").strip() if child is not None else ""


def _int(value: str, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_fritz_datetime(value: str) -> str | None:
    """Convert the box's ``dd.mm.yy HH:MM`` timestamps to ISO 8601 (``YYYY-MM-DDTHH:MM``)."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return dt.datetime.strptime(value, "%d.%m.%y %H:%M").isoformat(timespec="minutes")
    except ValueError:
        return value


def parse_duration_minutes(value: str) -> int | None:
    """Convert ``h:mm`` durations (minutes rounded up by the box) to a minute count."""
    value = (value or "").strip()
    if not value or ":" not in value:
        return None
    hours, minutes = value.split(":", 1)
    h, m = _int(hours), _int(minutes)
    if h is None or m is None:
        return None
    return h * 60 + m


def _root(xml: bytes | str) -> ET.Element:
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    return ET.fromstring(xml)


def parse_call_list(xml: bytes | str) -> dict[str, Any]:
    """Parse the call list XML (``X_AVM-DE_OnTel:GetCallList`` URL)."""
    root = _root(xml)
    calls: list[dict[str, Any]] = []
    for node in root.findall("Call"):
        type_id = _int(_text(node, "Type"))
        port = _text(node, "Port")
        port_id = _int(port)
        calls.append(
            {
                "id": _int(_text(node, "Id")),
                "type_id": type_id,
                "type": CALL_TYPES.get(type_id, "unknown") if type_id is not None else "unknown",
                "date": parse_fritz_datetime(_text(node, "Date")),
                "caller": _text(node, "Caller"),
                "caller_number": _text(node, "CallerNumber"),
                "called": _text(node, "Called"),
                "called_number": _text(node, "CalledNumber"),
                "name": _text(node, "Name"),
                "device": _text(node, "Device"),
                "port": port,
                "duration_minutes": parse_duration_minutes(_text(node, "Duration")),
                "number_type": _text(node, "Numbertype"),
                "count": _int(_text(node, "Count")),
                "recording_path": _text(node, "Path") or None,
                "is_fax": port_id == 5,
                "is_answering_machine": port_id is not None and (port_id == 6 or 40 <= port_id <= 49),
            }
        )
    return {"timestamp": _int(_text(root, "timestamp")), "calls": calls}


def parse_tam_list(xml: bytes | str) -> dict[str, Any]:
    """Parse ``X_AVM-DE_TAM:GetList`` (global TAM state plus one item per answering machine)."""
    root = _root(xml)
    machines = [
        {
            "index": _int(_text(item, "Index")),
            "name": _text(item, "Name"),
            "enabled": _text(item, "Enable") == "1",
            "displayed": _text(item, "Display") == "1",
        }
        for item in root.findall("Item")
    ]
    status = _int(_text(root, "Status"), 0) or 0
    return {
        "running": _text(root, "TAMRunning") == "1",
        "stick": _int(_text(root, "Stick")),
        "busy": bool(status & 0b01),
        "no_space_left": bool(status & 0b10),
        "remaining_minutes": _int(_text(root, "Capacity")),
        "answering_machines": machines,
    }


def parse_tam_messages(xml: bytes | str) -> list[dict[str, Any]]:
    """Parse the message list XML of one answering machine (``X_AVM-DE_TAM:GetMessageList`` URL)."""
    root = _root(xml)
    messages: list[dict[str, Any]] = []
    for node in root.findall("Message"):
        messages.append(
            {
                "index": _int(_text(node, "Index")),
                "tam_index": _int(_text(node, "Tam")),
                "date": parse_fritz_datetime(_text(node, "Date")),
                "caller_number": _text(node, "Number"),
                "caller_name": _text(node, "Name"),
                "called": _text(node, "Called"),
                "duration_minutes": parse_duration_minutes(_text(node, "Duration")),
                "in_phonebook": _text(node, "Inbook") == "1",
                # AVM's spec documents <New> inverted ("0 message is new"); real boxes send 1 for new.
                "new": _text(node, "New") == "1",
                "recording_path": _text(node, "Path") or None,
            }
        )
    return messages


def parse_deflections(xml: bytes | str) -> list[dict[str, Any]]:
    """Parse ``X_AVM-DE_OnTel:GetDeflections`` (call forwarding rules)."""
    root = _root(xml)
    result: list[dict[str, Any]] = []
    for item in root.findall("Item"):
        mode = _text(item, "Mode")
        type_ = _text(item, "Type")
        result.append(
            {
                "id": _int(_text(item, "DeflectionId")),
                "enabled": _text(item, "Enable") == "1",
                "type": type_,
                "type_description": DEFLECTION_TYPES.get(type_, type_),
                "number": _text(item, "Number"),
                "forward_to": _text(item, "DeflectionToNumber"),
                "mode": mode,
                "mode_description": DEFLECTION_MODES.get(mode, mode),
                "outgoing": _text(item, "Outgoing"),
                "phonebook_id": _int(_text(item, "PhonebookID")),
            }
        )
    return result


def parse_phonebook(xml: bytes | str) -> dict[str, Any]:
    """Parse a phonebook XML (regular phonebooks and the call barring list share this format)."""
    root = _root(xml)
    book = root.find("phonebook") if root.tag == "phonebooks" else root
    contacts = [parse_contact(node) for node in (book.findall("contact") if book is not None else [])]
    return {
        "name": book.get("name", "") if book is not None else "",
        "timestamp": _int(_text(book, "timestamp")) if book is not None else None,
        "contacts": contacts,
    }


def parse_contact(node: ET.Element) -> dict[str, Any]:
    """Parse one ``<contact>`` element."""
    person = node.find("person")
    telephony = node.find("telephony")
    numbers = []
    if telephony is not None:
        for num in telephony.findall("number"):
            numbers.append(
                {
                    "number": (num.text or "").strip(),
                    "type": num.get("type", ""),
                    "quickdial": num.get("quickdial", "") or "",
                    "vanity": num.get("vanity", "") or "",
                    "priority": num.get("prio", "0") == "1",
                }
            )
    emails = [(e.text or "").strip() for e in telephony.findall("services/email")] if telephony is not None else []
    category = _text(node, "category")
    return {
        "uniqueid": _int(_text(node, "uniqueid")),
        "name": _text(person, "realName"),
        "vip": category == "1",
        "numbers": numbers,
        "emails": [e for e in emails if e],
    }


def parse_contact_entry(xml: bytes | str) -> dict[str, Any]:
    """Parse the single-``<contact>`` document returned by ``GetCallBarringEntry``/``GetPhonebookEntry``."""
    root = _root(xml)
    node = root if root.tag == "contact" else root.find(".//contact")
    if node is None:
        raise ValueError("no <contact> element in phonebook entry data")
    return parse_contact(node)


def build_contact_xml(number: str, name: str = "", *, uniqueid: int | None = None, number_type: str = "home") -> str:
    """Build the ``<contact>`` document expected by ``SetCallBarringEntry`` / ``SetPhonebookEntry``."""
    number = number.strip()
    if not number:
        raise ValueError("number must not be empty")
    uid = f"<uniqueid>{uniqueid}</uniqueid>" if uniqueid is not None else ""
    safe_name = _escape(name.strip())
    return (
        "<?xml version='1.0' encoding='utf-8'?>"
        "<contact><category>0</category>"
        f"<person><realName>{safe_name}</realName></person>"
        "<telephony>"
        f'<number type="{_escape(number_type)}" prio="1" id="0">{_escape(number)}</number>'
        "</telephony>"
        f"{uid}</contact>"
    )


def parse_number_list(xml: bytes | str) -> list[dict[str, Any]]:
    """Parse ``X_VoIP:X_AVM-DE_GetNumbers`` - a ``<List>`` of ``<Item>`` elements with arbitrary children."""
    root = _root(xml)
    items: list[dict[str, Any]] = []
    for item in root.findall("Item"):
        items.append({child.tag.lower(): (child.text or "").strip() for child in item})
    return items


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
