import httpx
import pytest

from hsb_economy import state


def test_round_trip(tmp_path):
    data = state.empty() | {"sales": {"seen": ["a"]}}
    state.save(tmp_path / "s.json.gz", data)
    assert state.load(tmp_path / "s.json.gz", None) == data


def test_recovers_from_published_copy(tmp_path, monkeypatch):
    published = state.empty() | {"sales": {"seen": ["b"]}}
    requested = []

    def fake_get(url, **_):
        requested.append(url)
        return httpx.Response(200, content=state.encode(published), request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    assert state.load(tmp_path / "missing.json.gz", "https://example.test/") == published
    assert requested == ["https://example.test/v1/state.json.gz"]


def test_first_run_starts_fresh_on_404(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, **_: httpx.Response(404, request=httpx.Request("GET", url)))
    assert state.load(tmp_path / "missing.json.gz", "https://example.test") == state.empty()


def test_other_recovery_failures_abort(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, **_: httpx.Response(503, request=httpx.Request("GET", url)))
    with pytest.raises(httpx.HTTPStatusError):
        state.load(tmp_path / "missing.json.gz", "https://example.test")
