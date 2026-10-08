import pytest

from fritzmoles_mcp import server
from fritzmoles_mcp.client import FritzTelephony

READ_TOOL_NAMES = {
    "get_call_list",
    "get_own_numbers",
    "list_answering_machines",
    "get_answering_machine",
    "list_voicemails",
    "list_call_barrings",
    "get_call_barring",
    "list_call_forwardings",
    "get_call_forwarding",
    "list_phonebooks",
    "search_phonebook",
}
WRITE_TOOL_NAMES = {
    "set_answering_machine_enabled",
    "mark_voicemail",
    "delete_voicemail",
    "download_voicemail",
    "add_call_barring",
    "remove_call_barring",
    "set_call_forwarding_enabled",
    "dial_number",
    "hangup",
}


@pytest.fixture
def fake_client(client: FritzTelephony, monkeypatch) -> FritzTelephony:
    monkeypatch.setattr(server, "_client", client)
    return client


@pytest.mark.anyio
async def test_all_tools_registered():
    names = {t.name for t in await server.mcp.list_tools()}
    assert names >= READ_TOOL_NAMES
    tool = next(t for t in await server.mcp.list_tools() if t.name == "get_call_list")
    assert "kind" in tool.input_schema["properties"]


@pytest.mark.anyio
async def test_read_only_server_hides_write_tools():
    ro = server.create_server(read_only=True)
    names = {t.name for t in await ro.list_tools()}
    assert names == READ_TOOL_NAMES
    rw = server.create_server(read_only=False)
    assert {t.name for t in await rw.list_tools()} == READ_TOOL_NAMES | WRITE_TOOL_NAMES


@pytest.mark.anyio
async def test_get_call_list_via_dispatch(fake_client):
    result = await server.mcp.call_tool("get_call_list", {"kind": "missed", "days": 3})
    assert result.is_error is False
    assert [c["id"] for c in result.structured_content["calls"]] == [121]


@pytest.mark.anyio
async def test_list_voicemails_via_dispatch(fake_client):
    result = await server.mcp.call_tool("list_voicemails", {"tam_index": 0, "only_new": True})
    assert result.structured_content["result"][0]["index"] == 3


@pytest.mark.anyio
async def test_write_tool_via_dispatch(fake_client, connection):
    connection.responses[("X_AVM-DE_OnTel1", "SetCallBarringEntry")] = {"NewPhonebookEntryUniqueID": 7}
    result = await server.mcp.call_tool("add_call_barring", {"number": "0900123", "name": "Teuer"})
    assert result.structured_content == {"status": "ok", "uniqueid": 7, "number": "0900123", "name": "Teuer"}


def test_errors_are_returned_not_raised(fake_client, connection):
    connection.responses[("X_AVM-DE_TAM1", "SetEnable")] = RuntimeError("boom")
    assert server.set_answering_machine_enabled(0, True) == {"error": "RuntimeError: boom"}
    assert server.get_call_list(kind="bogus")["error"].startswith("ValueError")


def test_remove_call_barring_variants(fake_client, connection):
    connection.responses[("X_AVM-DE_OnTel1", "DeleteCallBarringEntryUID")] = {}
    assert server.remove_call_barring(uniqueid=42) == {"status": "ok", "removed": [42]}
    assert server.remove_call_barring(number="0800111222") == {"status": "ok", "removed": [42]}
    assert "no call barring" in server.remove_call_barring(number="123")["error"]
    assert "either" in server.remove_call_barring()["error"]


def test_simple_write_tools(fake_client, connection, tmp_path):
    connection.responses[("X_AVM-DE_TAM1", "MarkMessage")] = {}
    connection.responses[("X_AVM-DE_TAM1", "DeleteMessage")] = {}
    connection.responses[("X_AVM-DE_OnTel1", "SetDeflectionEnable")] = {}
    connection.responses[("X_VoIP1", "X_AVM-DE_DialNumber")] = {}
    connection.responses[("X_VoIP1", "X_AVM-DE_DialHangup")] = {}
    assert server.mark_voicemail(0, 3)["status"] == "ok"
    assert server.delete_voicemail(0, 3)["deleted"] is True
    assert server.set_call_forwarding_enabled(1, False)["enabled"] is False
    assert server.dial_number("0123")["status"] == "ok"
    assert server.hangup() == {"status": "ok"}
    assert server.download_voicemail(0, 3, str(tmp_path))["bytes"] > 0


def test_read_tools(fake_client, connection):
    connection.responses[("X_AVM-DE_TAM1", "GetInfo")] = {"NewName": "AB", "NewStatus": 0}
    connection.responses[("X_AVM-DE_OnTel1", "GetDeflection")] = {"NewEnable": False}
    connection.responses[("X_AVM-DE_OnTel1", "GetCallBarringEntryByNum")] = {
        "NewPhonebookEntryData": "<contact><uniqueid>1</uniqueid></contact>"
    }
    assert server.get_own_numbers()["result"][0]["name"] == "Büro"
    assert server.list_answering_machines()["running"] is True
    assert server.get_answering_machine(0)["name"] == "AB"
    assert server.list_call_barrings()["result"][0]["uniqueid"] == 42
    assert server.get_call_barring("1")["uniqueid"] == 1
    assert server.list_call_forwardings()["result"][1]["id"] == 1
    assert server.get_call_forwarding(0)["enabled"] is False
    assert server.list_phonebooks()["result"][0]["id"] == 0
    assert server.search_phonebook("max")["result"][0]["uniqueid"] == 1234


def test_get_client_connects_lazily(monkeypatch):
    server.reset_client()
    monkeypatch.delenv("FRITZ_USERNAME", raising=False)
    monkeypatch.delenv("FRITZ_PASSWORD", raising=False)
    monkeypatch.setattr(server.FritzConfig, "from_env", classmethod(lambda cls: cls()))
    assert "FRITZ_USERNAME" in server.get_call_list()["error"]
    server.reset_client()
