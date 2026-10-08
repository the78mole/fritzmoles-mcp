"""Shared fixtures: a fake TR-064 connection + fake URL fetcher instead of a live FRITZ!Box."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fritzmoles_mcp.client import FritzTelephony

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeConnection:
    """Records every call_action and answers from a (service, action) -> response table."""

    def __init__(self, responses: dict[tuple[str, str], Any] | None = None) -> None:
        self.responses = dict(responses or {})
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def call_action(self, service_name: str, action_name: str, **kwargs: Any) -> dict[str, Any]:
        arguments = kwargs.get("arguments") or {k: v for k, v in kwargs.items() if k != "arguments"}
        self.calls.append((service_name, action_name, dict(arguments)))
        key = (service_name, action_name)
        if key not in self.responses:
            raise AssertionError(f"unexpected TR-064 call {key} with {arguments}")
        response = self.responses[key]
        if callable(response):
            return response(arguments)
        if isinstance(response, Exception):
            raise response
        return response


class FakeFetch:
    def __init__(self, pages: dict[str, bytes] | None = None) -> None:
        self.pages = dict(pages or {})
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        for prefix, data in self.pages.items():
            if url.startswith(prefix):
                return data
        raise AssertionError(f"unexpected fetch of {url}")


DEFAULT_RESPONSES: dict[tuple[str, str], Any] = {
    ("X_AVM-DE_OnTel1", "GetCallList"): {"NewCallListURL": "http://fritz.box:49000/calllist.lua?sid=abc"},
    ("X_AVM-DE_OnTel1", "GetCallBarringList"): {"NewPhonebookURL": "http://fritz.box:49000/barring.lua?sid=abc"},
    ("X_AVM-DE_OnTel1", "GetDeflections"): {"NewDeflectionList": fixture_bytes("deflections.xml").decode()},
    ("X_AVM-DE_OnTel1", "GetPhonebookList"): {"NewPhonebookList": "0,1"},
    ("X_AVM-DE_OnTel1", "GetPhonebook"): lambda args: {
        "NewPhonebookName": f"Telefonbuch {args['NewPhonebookID']}",
        "NewPhonebookURL": f"http://fritz.box:49000/pb{args['NewPhonebookID']}.lua?sid=abc",
        "NewPhonebookExtraID": "",
    },
    ("X_AVM-DE_TAM1", "GetList"): {"NewTAMList": fixture_bytes("tamlist.xml").decode()},
    ("X_AVM-DE_TAM1", "GetMessageList"): {"NewURL": "http://fritz.box:49000/tammessages.lua?sid=abc"},
    ("X_VoIP1", "X_AVM-DE_GetNumbers"): {"NewNumberList": fixture_bytes("numbers.xml").decode()},
}

DEFAULT_PAGES: dict[str, bytes] = {
    "http://fritz.box:49000/calllist.lua": fixture_bytes("calllist.xml"),
    "http://fritz.box:49000/barring.lua": fixture_bytes("barring.xml"),
    "http://fritz.box:49000/pb0.lua": fixture_bytes("phonebook.xml"),
    "http://fritz.box:49000/pb1.lua": fixture_bytes("phonebook.xml"),
    "http://fritz.box:49000/tammessages.lua": fixture_bytes("tammessages.xml"),
    "http://fritz.box:49000/download.lua": b"RIFF-fake-wav",
}


@pytest.fixture
def connection() -> FakeConnection:
    return FakeConnection(DEFAULT_RESPONSES)


@pytest.fixture
def fetch() -> FakeFetch:
    return FakeFetch(DEFAULT_PAGES)


@pytest.fixture
def client(connection: FakeConnection, fetch: FakeFetch) -> FritzTelephony:
    return FritzTelephony(connection, fetch, base_url="http://fritz.box:49000")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
