from pokerbot.webapp.server import create_app


def _client():
    app, _ = create_app()
    app.testing = True
    return app.test_client()


def test_index_is_served():
    r = _client().get("/")
    assert r.status_code == 200 and b"Poker Bot" in r.data


def test_state_starts_idle():
    s = _client().get("/api/state").get_json()
    assert s["running"] is False
    assert s["hand"] is None and s["decision"] is None
    assert s["session"] == {"hands": 0, "net_bb": 0.0}


def test_profiles_is_a_list():
    r = _client().get("/api/profiles")
    assert r.status_code == 200 and isinstance(r.get_json(), list)


def test_config_endpoint():
    c = _client().get("/api/config").get_json()
    assert "bb" in c and "mode" in c


def test_analyze_is_blocked_while_the_bot_runs():
    # the bot thread holds its own SQLite connection, a mid-session rebuild risks
    # 'database is locked', so /api/analyze must refuse while running
    import threading
    app, ctrl = create_app()
    app.testing = True
    ctrl.thread = threading.current_thread()      # alive -> ctrl.running() is True
    r = app.test_client().post("/api/analyze").get_json()
    assert r["ok"] is False and "stop the bot" in r["error"]
