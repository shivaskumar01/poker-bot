import random

import pokerbot.io.email_inbox as ei
from pokerbot.io.email_inbox import TempInbox


def test_create_and_read_code(monkeypatch):
    created = {"ok": False}

    def fake_req(method, path, token=None, data=None):
        if path == "/domains":
            return {"hydra:member": [{"domain": "mail.tm", "isActive": True}]}
        if path == "/accounts":
            created["ok"] = True
            return {"id": "1", "address": data["address"]}
        if path == "/token":
            return {"token": "JWT123"}
        if path == "/messages":
            assert token == "JWT123"
            return {"hydra:member": [{"id": "m1", "from": {"address": "no-reply@pokernow.com"},
                                      "subject": "PokerNow login", "intro": "code 731902 ..."}]}
        if path.startswith("/messages/"):
            return {"text": "Your PokerNow login code is 731902.", "html": []}
        return {}

    monkeypatch.setattr(ei, "_req", fake_req)
    box = TempInbox.create(random.Random(0))
    assert created["ok"] and box.address.endswith("@mail.tm")
    assert box.poll_once() == "731902"


def test_poll_once_returns_none_when_empty(monkeypatch):
    monkeypatch.setattr(ei, "_req",
                        lambda method, path, token=None, data=None: {"hydra:member": []})
    box = TempInbox("a@mail.tm", "JWT")
    assert box.poll_once() is None


def test_poll_once_swallows_network_errors(monkeypatch):
    def boom(method, path, token=None, data=None):
        raise OSError("mail.tm unreachable")

    notes = []
    monkeypatch.setattr(ei, "_req", boom)
    box = TempInbox("a@mail.tm", "JWT")
    assert box.poll_once(log=notes.append) is None     # degrades, never raises into the login loop
    assert any("poll error" in n for n in notes)
