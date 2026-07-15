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


def test_persona_home():
    h = data.persona_home("S01")
    assert h and h["ordinary"] > 0
    assert len(h["transactions"]) == 5 and len(h["messages"]) >= 4
    # S01's top-recommended campaign is C1 -> the 普通預金 campaign
    assert h["banner"] and h["banner"]["id"] == "CMP-DEP-2026Q3-01"
    # determinism
    assert data.persona_home("S01")["ordinary"] == h["ordinary"]

    r = client.get("/ui/persona/S01/home")
    assert r.status_code == 200
    assert "普通預金残高" in r.text and "最近の取引" in r.text and "お知らせ" in r.text
    assert 'data-home-tab="campaign"' in r.text  # bottom nav wired
    assert client.get("/ui/persona/NOPE/home").status_code == 404


def test_campaign_detail_renders_markdown():
    r = client.get("/ui/campaign/CMP-DEP-2026Q3-01")
    assert r.status_code == 200
    # the block's condition table + cap survive into rendered HTML
    assert "<table>" in r.text and "給与または年金の受取口座に設定" in r.text
    assert "4,000円" in r.text
    # the facts yaml block must NOT leak into a campaign's detail
    assert "```" not in r.text and "reward:" not in r.text
    assert client.get("/ui/campaign/NOPE").status_code == 404


def test_campaign_concierge_split_view():
    r = client.get("/ui/campaign/CMP-DEP-2026Q3-01/concierge")
    assert r.status_code == 200
    # top panel = the same detail; bottom panel = chat widget
    assert 'class="c-detail"' in r.text and "給与または年金の受取口座に設定" in r.text
    assert 'id="c-chat-form"' in r.text and "AIコンシェルジュ" in r.text
    assert client.get("/ui/campaign/NOPE/concierge").status_code == 404
