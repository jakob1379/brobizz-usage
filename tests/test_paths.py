from __future__ import annotations

from brobizz_usage import get_user_data_path


def test_user_data_path_uses_xdg_data_home(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    path = get_user_data_path("trips.json")

    assert path == tmp_path / "brobizz-usage" / "trips.json"
