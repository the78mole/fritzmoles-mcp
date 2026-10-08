from pathlib import Path

import pytest

from fritzmoles_mcp.client import FritzTelephony, _normalize_number, _with_query

from .conftest import FakeConnection, FakeFetch


def test_with_query():
    assert _with_query("http://x/a.lua?sid=1", days=3, max=None) == "http://x/a.lua?sid=1&days=3"
    assert _with_query("http://x/a.lua", max=5) == "http://x/a.lua?max=5"
    assert _with_query("http://x/a.lua?sid=1") == "http://x/a.lua?sid=1"


def test_normalize_number():
    assert _normalize_number("+49 (30) 999-888") == "+4930999888"
    assert _normalize_number("") == ""


def test_get_calls_all_and_filtered(client, fetch):
    data = client.get_calls(days=7, max_entries=10)
    assert data["kind"] == "all"
    assert len(data["calls"]) == 4
    assert fetch.urls[-1] == "http://fritz.box:49000/calllist.lua?sid=abc&days=7&max=10"
    missed = client.get_calls("missed")["calls"]
    assert [c["id"] for c in missed] == [121]
    assert [c["id"] for c in client.get_calls("incoming")["calls"]] == [122]
    assert [c["id"] for c in client.get_calls("rejected")["calls"]] == [120]
    assert client.get_calls("active")["calls"] == []


def test_get_calls_rejects_unknown_kind(client):
    with pytest.raises(ValueError, match="unknown call kind"):
        client.get_calls("bogus")


def test_get_calls_disabled_feature(fetch):
    fc = FakeConnection({("X_AVM-DE_OnTel1", "GetCallList"): {"NewCallListURL": ""}})
    with pytest.raises(RuntimeError, match="disabled"):
        FritzTelephony(fc, fetch).get_calls()


def test_own_numbers(client):
    numbers = client.get_own_numbers()
    assert numbers[0]["number"] == "0123456789"


def test_dial_and_hangup(connection, fetch):
    connection.responses[("X_VoIP1", "X_AVM-DE_DialNumber")] = {}
    connection.responses[("X_VoIP1", "X_AVM-DE_DialHangup")] = {}
    client = FritzTelephony(connection, fetch)
    client.dial(" +49301234 ")
    assert connection.calls[-1] == ("X_VoIP1", "X_AVM-DE_DialNumber", {"NewX_AVM-DE_PhoneNumber": "+49301234"})
    client.hangup()
    assert connection.calls[-1][1] == "X_AVM-DE_DialHangup"
    with pytest.raises(ValueError):
        client.dial("call me; rm -rf")


def test_answering_machines(connection, client):
    tams = client.list_answering_machines()
    assert tams["answering_machines"][0]["name"] == "Anrufbeantworter"
    connection.responses[("X_AVM-DE_TAM1", "GetInfo")] = {
        "NewEnable": True,
        "NewName": "AB Büro",
        "NewTAMRunning": True,
        "NewStick": 0,
        "NewStatus": 1,
        "NewCapacity": 55,
        "NewMode": "record_message",
        "NewRingSeconds": 20,
        "NewPhoneNumbers": "0123456789, 0123456790",
    }
    info = client.get_answering_machine(0)
    assert info["busy"] is True and info["no_space_left"] is False
    assert info["phone_numbers"] == ["0123456789", "0123456790"]
    assert info["mode"] == "record_message"
    connection.responses[("X_AVM-DE_TAM1", "GetInfo")]["NewPhoneNumbers"] = ""
    assert client.get_answering_machine(0)["phone_numbers"] == "all"
    connection.responses[("X_AVM-DE_TAM1", "SetEnable")] = {}
    client.set_answering_machine_enabled(1, False)
    assert connection.calls[-1] == ("X_AVM-DE_TAM1", "SetEnable", {"NewIndex": 1, "NewEnable": False})


def test_voicemails(connection, client, fetch):
    all_msgs = client.list_voicemails(0, max_entries=20)
    assert fetch.urls[-1] == "http://fritz.box:49000/tammessages.lua?sid=abc&max=20"
    assert [m["index"] for m in all_msgs] == [3, 0]
    assert [m["index"] for m in client.list_voicemails(0, only_new=True)] == [3]
    connection.responses[("X_AVM-DE_TAM1", "MarkMessage")] = {}
    connection.responses[("X_AVM-DE_TAM1", "DeleteMessage")] = {}
    client.mark_voicemail(0, 3, read=False)
    assert connection.calls[-1][2] == {"NewIndex": 0, "NewMessageIndex": 3, "NewMarkedAsRead": False}
    client.delete_voicemail(0, 3)
    assert connection.calls[-1][1] == "DeleteMessage"


def test_download_voicemail(client, fetch, tmp_path: Path):
    result = client.download_voicemail(0, 3, tmp_path / "vm")
    assert fetch.urls[-1] == "http://fritz.box:49000/download.lua?path=/data/tam/rec/rec.0.003&sid=abc"
    file = Path(result["file"])
    assert file.read_bytes() == b"RIFF-fake-wav"
    assert file.name == "tam0_msg3_2011-09-23T08-13_555123456.wav"
    assert result["bytes"] == len(b"RIFF-fake-wav")
    with pytest.raises(LookupError, match="no message"):
        client.download_voicemail(0, 99, tmp_path)


def test_download_voicemail_without_path(connection, fetch, tmp_path):
    fetch.pages["http://fritz.box:49000/tammessages.lua"] = b"<Root><Message><Index>1</Index></Message></Root>"
    client = FritzTelephony(connection, fetch, base_url="http://fritz.box:49000")
    with pytest.raises(LookupError, match="no recording"):
        client.download_voicemail(0, 1, tmp_path)


def test_download_voicemail_with_full_download_path(connection, fetch, tmp_path):
    fetch.pages["http://fritz.box:49000/tammessages.lua"] = (
        b"<Root><Message><Index>1</Index><Path>/download.lua?path=/data/tam/rec/rec.0.001</Path></Message></Root>"
    )
    client = FritzTelephony(connection, fetch, base_url="http://fritz.box:49000")
    assert client.download_voicemail(0, 1, tmp_path)["bytes"] > 0
    assert fetch.urls[-1] == "http://fritz.box:49000/download.lua?path=/data/tam/rec/rec.0.001&sid=abc"


def test_voicemail_list_url_missing(fetch):
    fc = FakeConnection({("X_AVM-DE_TAM1", "GetMessageList"): {"NewURL": ""}})
    with pytest.raises(RuntimeError, match="no message list URL"):
        FritzTelephony(fc, fetch).list_voicemails(0)


def test_call_barrings(connection, client):
    entries = client.list_call_barrings()
    assert [e["uniqueid"] for e in entries] == [42, 43]
    connection.responses[("X_AVM-DE_OnTel1", "SetCallBarringEntry")] = {"NewPhonebookEntryUniqueID": 99}
    uid = client.add_call_barring("0900 123", "Teuer")
    assert uid == 99
    service, action, args = connection.calls[-1]
    assert (service, action) == ("X_AVM-DE_OnTel1", "SetCallBarringEntry")
    assert "<realName>Teuer</realName>" in args["NewPhonebookEntryData"]
    assert ">0900 123</number>" in args["NewPhonebookEntryData"]
    client.add_call_barring("0900 124")
    assert "<realName>Sperre 0900 124</realName>" in connection.calls[-1][2]["NewPhonebookEntryData"]

    connection.responses[("X_AVM-DE_OnTel1", "DeleteCallBarringEntryUID")] = {}
    client.remove_call_barring(42)
    assert connection.calls[-1][2] == {"NewPhonebookEntryUniqueID": 42}
    assert client.remove_call_barring_by_number("+49 30 999888") == [43]
    assert client.remove_call_barring_by_number("000") == []

    connection.responses[("X_AVM-DE_OnTel1", "GetCallBarringEntryByNum")] = {
        "NewPhonebookEntryData": "<contact><person><realName>W</realName></person><uniqueid>42</uniqueid></contact>"
    }
    entry = client.get_call_barring_by_number("0800111222")
    assert entry["uniqueid"] == 42 and entry["blocked"] is True
    connection.responses[("X_AVM-DE_OnTel1", "GetCallBarringEntryByNum")] = RuntimeError("UPnPError: errorCode: 714")
    assert client.get_call_barring_by_number("1") == {"blocked": False, "number": "1"}
    connection.responses[("X_AVM-DE_OnTel1", "GetCallBarringEntryByNum")] = RuntimeError("UPnPError: errorCode: 820")
    with pytest.raises(RuntimeError, match="820"):
        client.get_call_barring_by_number("1")


def test_call_forwardings(connection, client):
    rules = client.list_call_forwardings()
    assert [r["id"] for r in rules] == [0, 1]
    connection.responses[("X_AVM-DE_OnTel1", "GetDeflection")] = {
        "NewEnable": True,
        "NewType": "fromAll",
        "NewNumber": "",
        "NewDeflectionToNumber": "0171123",
        "NewMode": "eImmediately",
        "NewOutgoing": "",
        "NewPhonebookID": 0,
    }
    rule = client.get_call_forwarding(1)
    assert rule["forward_to"] == "0171123"
    assert rule["type_description"] == "all callers"
    assert rule["mode_description"] == "immediately"
    connection.responses[("X_AVM-DE_OnTel1", "SetDeflectionEnable")] = {}
    client.set_call_forwarding_enabled(1, True)
    assert connection.calls[-1] == ("X_AVM-DE_OnTel1", "SetDeflectionEnable", {"NewDeflectionId": 1, "NewEnable": True})


def test_phonebooks(client):
    books = client.list_phonebooks()
    assert [(b["id"], b["name"]) for b in books] == [(0, "Telefonbuch 0"), (1, "Telefonbuch 1")]
    book = client.get_phonebook(0)
    assert book["id"] == 0 and book["name"] == "Telefonbuch"
    assert [c["name"] for c in client.search_phonebook("glaser")] == ["Elektro Glaser"]
    assert [c["name"] for c in client.search_phonebook("0171 2345")] == ["Max Mustermann"]
    assert client.search_phonebook("nobody") == []
    assert client.search_phonebook("") == []


def test_empty_phonebook_list():
    fc = FakeConnection({("X_AVM-DE_OnTel1", "GetPhonebookList"): {"NewPhonebookList": ""}})
    assert FritzTelephony(fc, FakeFetch()).list_phonebooks() == []


def test_connect_requires_credentials():
    from fritzmoles_mcp.config import FritzConfig

    with pytest.raises(ValueError):
        FritzTelephony.connect(FritzConfig())
