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
    assert box.wait_for_code(timeout=5, sleep=lambda s: None) == "731902"


def test_wait_for_code_times_out_when_empty(monkeypatch):
    monkeypatch.setattr(ei, "_req",
                        lambda method, path, token=None, data=None: {"hydra:member": []})
    box = TempInbox("a@mail.tm", "JWT")
    assert box.wait_for_code(timeout=0.2, sleep=lambda s: None) is None


def test_wait_for_code_honors_stop(monkeypatch):
    monkeypatch.setattr(ei, "_req",
                        lambda method, path, token=None, data=None: {"hydra:member": []})
    box = TempInbox("a@mail.tm", "JWT")
    assert box.wait_for_code(timeout=60, sleep=lambda s: None, should_stop=lambda: True) is None
