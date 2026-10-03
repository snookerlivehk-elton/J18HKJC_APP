"""Tests for ad_poster_guard — cloned poster detection / rebuild."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ad_poster_guard import (
    assert_poster_not_foreign_clone,
    find_cloned_poster_groups,
    payloads_from_package_tips,
    poster_sha256,
    regenerate_poster_png_from_package,
    repair_cloned_ad_posters,
    repair_package_poster,
)


def _pkg(*, ad_id: str, date: str, course: str = "ST", created: str) -> dict:
    return {
        "id": ad_id,
        "status": "ready",
        "created_at": created,
        "meeting": {
            "date": date,
            "weekday": "星期日",
            "venue": "沙田",
            "venue_code": course,
            "session": "日",
        },
        "tips": [
            {
                "race": 1,
                "horses": [
                    {"no": 1, "name": "測試一"},
                    {"no": 2, "name": "測試二"},
                    {"no": 3, "name": "測試三"},
                    {"no": 4, "name": "測試四"},
                ],
            },
            {
                "race": 2,
                "horses": [
                    {"no": 5, "name": "測試五"},
                    {"no": 6, "name": "測試六"},
                ],
            },
        ],
        "copy": {"facebook": "x", "ai": {"title": "t", "featured": []}},
        "assets": {},
        "meta": {},
    }


def test_payloads_from_tips_uses_meeting_date():
    pkg = _pkg(
        ad_id="2026-10-04-st-day",
        date="2026-10-04",
        created="2026-10-04T00:00:00+08:00",
    )
    payloads = payloads_from_package_tips(pkg)
    assert len(payloads) == 2
    assert payloads[0].racing_date == "2026-10-04"
    assert payloads[0].course == "ST"
    assert payloads[0].race_num == 1
    assert payloads[0].fused_picks[0].horse_name == "測試一"


def test_regenerate_poster_png_embeds_correct_date(tmp_path: Path):
    pkg = _pkg(
        ad_id="2026-10-04-st-day",
        date="2026-10-04",
        created="2026-10-04T00:00:00+08:00",
    )
    png = regenerate_poster_png_from_package(pkg)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 50_000
    # 同 tips／日期再畫一次應穩定產出（非另一賽日舊圖）
    png2 = regenerate_poster_png_from_package(pkg)
    assert poster_sha256(png) == poster_sha256(png2)

    pkg_old = dict(pkg)
    pkg_old["meeting"] = dict(pkg["meeting"])
    pkg_old["meeting"]["date"] = "2026-10-01"
    pkg_old["id"] = "2026-10-01-st-day"
    png_old = regenerate_poster_png_from_package(pkg_old)
    assert poster_sha256(png) != poster_sha256(png_old)


def test_find_cloned_groups_and_repair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from ad_package import package_paths, save_ad_package

    monkeypatch.setenv("USE_SQLITE", "true")
    monkeypatch.setenv("AD_STORE_ENABLED", "false")
    monkeypatch.setenv("AD_POSTER_CLONE_REPAIR", "true")

    root = tmp_path / "ad_out"
    root.mkdir()

    # 兩個賽日共用同一張「舊」海報 bytes
    stale = b"FAKE_PNG_SAME_BYTES_FOR_BOTH_MEETINGS"
    p1 = _pkg(
        ad_id="2026-10-01-st-day",
        date="2026-10-01",
        created="2026-10-01T12:00:00+08:00",
    )
    p2 = _pkg(
        ad_id="2026-10-04-st-day",
        date="2026-10-04",
        created="2026-10-04T08:00:00+08:00",
    )

    for pkg in (p1, p2):
        paths = package_paths(str(pkg["id"]), root)
        paths["root"].mkdir(parents=True, exist_ok=True)
        paths["poster"].write_bytes(stale)
        paths["json"].write_text(json.dumps(pkg, ensure_ascii=False), encoding="utf-8")

    # patch iterators to use disk packages we wrote
    import ad_poster_guard as guard

    def _fake_iter(_root):
        out = []
        for ad_id in ("2026-10-01-st-day", "2026-10-04-st-day"):
            data = json.loads(package_paths(ad_id, root)["json"].read_text(encoding="utf-8"))
            out.append(data)
        return out

    monkeypatch.setattr(guard, "_iter_ready_packages", _fake_iter)

    groups = find_cloned_poster_groups(_fake_iter(root), output_root=root)
    assert len(groups) == 1
    assert groups[0]["source_id"] == "2026-10-01-st-day"
    assert groups[0]["clone_ids"] == ["2026-10-04-st-day"]

    # repair uses real render — may need fonts/templates
    result = repair_package_poster(p2, output_root=root, notify=False)
    assert result.get("ok"), result
    assert result.get("new_sha256") != poster_sha256(stale)
    new_bytes = package_paths("2026-10-04-st-day", root)["poster"].read_bytes()
    assert new_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    # ingest guard rejects foreign clone
    with pytest.raises(ValueError, match="identical"):
        assert_poster_not_foreign_clone(
            stale,
            meeting_date="2026-10-04",
            output_root=root,
            force=False,
        )
    # same meeting date ok
    assert (
        assert_poster_not_foreign_clone(
            stale,
            meeting_date="2026-10-01",
            output_root=root,
            force=False,
        )
        is None
    )


def test_repair_cloned_ad_posters_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("USE_SQLITE", "true")
    monkeypatch.setenv("AD_STORE_ENABLED", "false")
    monkeypatch.setenv("AD_POSTER_CLONE_REPAIR", "true")

    root = tmp_path / "ad_out"
    root.mkdir()
    from ad_package import package_paths

    # Build two real different-date posters then force-clone bytes onto 10-04
    p1 = _pkg(
        ad_id="2026-10-01-st-day",
        date="2026-10-01",
        created="2026-10-01T12:00:00+08:00",
    )
    real_1001 = regenerate_poster_png_from_package(p1)
    p2 = _pkg(
        ad_id="2026-10-04-st-day",
        date="2026-10-04",
        created="2026-10-04T08:00:00+08:00",
    )
    # intentionally wrong: 10-04 id stores 10-01 bytes
    for pkg, blob in ((p1, real_1001), (p2, real_1001)):
        paths = package_paths(str(pkg["id"]), root)
        paths["root"].mkdir(parents=True, exist_ok=True)
        paths["poster"].write_bytes(blob)
        paths["json"].write_text(json.dumps(pkg, ensure_ascii=False), encoding="utf-8")

    import ad_poster_guard as guard

    def _fake_iter(_root):
        return [
            json.loads(package_paths(i, root)["json"].read_text(encoding="utf-8"))
            for i in ("2026-10-01-st-day", "2026-10-04-st-day")
        ]

    monkeypatch.setattr(guard, "_iter_ready_packages", _fake_iter)

    out = repair_cloned_ad_posters(output_root=root, notify=False)
    assert out.get("repaired"), out
    fixed = package_paths("2026-10-04-st-day", root)["poster"].read_bytes()
    kept = package_paths("2026-10-01-st-day", root)["poster"].read_bytes()
    assert poster_sha256(kept) == poster_sha256(real_1001)
    assert poster_sha256(fixed) != poster_sha256(real_1001)
