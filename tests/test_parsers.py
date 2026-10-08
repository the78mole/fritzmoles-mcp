import pytest

from fritzmoles_mcp import parsers

from .conftest import fixture_bytes


def test_parse_call_list_types_and_flags():
    data = parsers.parse_call_list(fixture_bytes("calllist.xml"))
    assert data["timestamp"] == 123456
    calls = data["calls"]
    assert [c["type"] for c in calls] == ["outgoing", "incoming", "missed", "rejected"]
    assert calls[0]["date"] == "2011-09-23T08:13"
    assert calls[0]["duration_minutes"] == 1
    assert calls[1]["is_answering_machine"] is True
    assert calls[1]["recording_path"].endswith("rec.0.000")
    assert calls[2]["count"] == 2
    assert calls[2]["port"] == ""
    assert calls[3]["is_fax"] is True
    assert calls[3]["is_answering_machine"] is False


def test_parse_call_list_unknown_type():
    xml = "<root><Call><Id>1</Id><Type>77</Type></Call><Call><Id>2</Id></Call></root>"
    calls = parsers.parse_call_list(xml)["calls"]
    assert calls[0]["type"] == "unknown"
    assert calls[1]["type"] == "unknown" and calls[1]["type_id"] is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("23.09.11 08:13", "2011-09-23T08:13"), ("", None), ("garbage", "garbage")],
)
def test_parse_fritz_datetime(raw, expected):
    assert parsers.parse_fritz_datetime(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [("0:01", 1), ("1:30", 90), ("", None), ("x", None), ("a:b", None)])
def test_parse_duration_minutes(raw, expected):
    assert parsers.parse_duration_minutes(raw) == expected


def test_parse_tam_list():
    data = parsers.parse_tam_list(fixture_bytes("tamlist.xml"))
    assert data["running"] is True
    assert data["busy"] is False
    assert data["no_space_left"] is True
    assert data["remaining_minutes"] == 77
    assert data["answering_machines"][0] == {"index": 0, "name": "Anrufbeantworter", "enabled": True, "displayed": True}
    assert data["answering_machines"][1]["enabled"] is False


def test_parse_tam_messages():
    messages = parsers.parse_tam_messages(fixture_bytes("tammessages.xml"))
    assert len(messages) == 2
    first = messages[0]
    assert first["index"] == 3
    assert first["new"] is True
    assert first["in_phonebook"] is True
    assert first["caller_number"] == "555123456"
    assert first["caller_name"] == "Max Mustermann"
    assert first["duration_minutes"] == 1
    assert first["recording_path"] == "/data/tam/rec/rec.0.003"
    assert messages[1]["new"] is False


def test_parse_deflections():
    rules = parsers.parse_deflections(fixture_bytes("deflections.xml"))
    assert rules[0]["id"] == 0
    assert rules[0]["enabled"] is True
    assert rules[0]["type_description"] == "specific number"
    assert rules[0]["mode_description"] == "immediately"
    assert rules[0]["forward_to"] == "987456"
    assert rules[1]["enabled"] is False
    assert rules[1]["mode_description"] == "when busy"
    assert rules[0]["kind"] == "forward"
    assert parsers.deflection_kind("eNoSignal") == "block"
    assert rules[1]["phonebook_id"] is None


def test_parse_phonebook_and_contacts():
    book = parsers.parse_phonebook(fixture_bytes("phonebook.xml"))
    assert book["name"] == "Telefonbuch"
    assert book["timestamp"] == 1700000001
    max_ = book["contacts"][0]
    assert max_["uniqueid"] == 1234
    assert max_["vip"] is True
    assert max_["emails"] == ["max@example.com"]
    assert max_["numbers"][0] == {
        "number": "030399760",
        "type": "work",
        "quickdial": "1",
        "vanity": "",
        "priority": False,
    }
    assert max_["numbers"][1]["priority"] is True
    assert book["contacts"][1]["vip"] is False


def test_parse_barring_list_uses_phonebook_format():
    book = parsers.parse_phonebook(fixture_bytes("barring.xml"))
    assert book["name"] == "Rufsperre"
    assert [c["uniqueid"] for c in book["contacts"]] == [42, 43]


def test_parse_contact_entry_single_and_wrapped():
    single = (
        "<contact><person><realName>X</realName></person>"
        "<telephony><number type='home'>1</number></telephony><uniqueid>7</uniqueid></contact>"
    )
    assert parsers.parse_contact_entry(single)["uniqueid"] == 7
    wrapped = f"<phonebooks><phonebook>{single}</phonebook></phonebooks>"
    assert parsers.parse_contact_entry(wrapped)["name"] == "X"
    with pytest.raises(ValueError):
        parsers.parse_contact_entry("<phonebooks/>")


def test_build_contact_xml_escapes_and_roundtrips():
    xml = parsers.build_contact_xml("0800 111 222", 'Spam & "Co"', uniqueid=5)
    contact = parsers.parse_contact_entry(xml)
    assert contact["name"] == 'Spam & "Co"'
    assert contact["numbers"][0]["number"] == "0800 111 222"
    assert contact["uniqueid"] == 5
    assert "<uniqueid>" not in parsers.build_contact_xml("1", "n")
    with pytest.raises(ValueError):
        parsers.build_contact_xml("   ")


def test_parse_number_list():
    items = parsers.parse_number_list(fixture_bytes("numbers.xml"))
    assert items == [
        {"number": "0123456789", "type": "eVoIP", "index": "0", "name": "Büro"},
        {"number": "0123456790", "type": "eVoIP", "index": "1", "name": "Fax"},
    ]
