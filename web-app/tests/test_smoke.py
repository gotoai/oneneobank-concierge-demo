"""Data-layer + endpoint smoke tests. No model needed."""
from fastapi.testclient import TestClient

from app import data
from app.main import app

client = TestClient(app)


def test_personas_parsed():
    ps = data.get_data().personas
    assert len(ps) >= 17
    p = {x["id"]: x for x in ps}
    assert p["S01"]["name"] == "Aoi"
    assert p["S01"]["type_label"] == "初任給で貯蓄を始める"
    assert p["S01"]["age"] == 24 and p["S01"]["gender"] == "女性"
    assert p["S01"]["emoji"] and p["S01"]["color"].startswith("hsl")
    # hard-case flag captured on a 難ケース persona
    assert any(x["hard_case"] for x in ps)


def test_campaigns_parsed():
    cs = data.get_data().campaigns
    ids = {c["id"] for c in cs}
    assert {"CMP-DEP-2026Q3-01", "CMP-LOAN-2026Q3-01", "CMP-DEBIT-2026Q3-01"} <= ids
    dep = next(c for c in cs if c["id"] == "CMP-DEP-2026Q3-01")
    assert dep["category"] == "預金" and dep["period"]
    assert dep["description"]


def test_index_serves_both_tabs():
    r = client.get("/")
    assert r.status_code == 200
    assert "ペルソナ" in r.text and "キャンペーン" in r.text
    assert "panel-personas" in r.text and "panel-campaigns" in r.text


def test_api_and_health():
    assert client.get("/api/personas").json()[0]["id"] == "S01"
    assert len(client.get("/api/campaigns").json()) == 4
    assert client.get("/healthz").json()["status"] == "ok"
