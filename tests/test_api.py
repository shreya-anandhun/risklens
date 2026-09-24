import pytest
from fastapi.testclient import TestClient

from app.main import app
from risklens import store

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(autouse=True)
def fresh_portfolio():
    store.reset()
    yield
    store.reset()


@pytest.fixture
def client():
    return TestClient(app)


GOOD = {"supplier_name": "Test Co", "lead_time_days": 40, "reliability_score": 0.85, "geopolitical_risk_index": 30, "weather_risk_level": "medium"}


def test_overview_and_meta(client):
    o = client.get("/api/overview").json()
    assert o["summary"]["n"] > 0 and len(o["timeline"]) > 30 and 0 <= o["catch_rate"] <= 100
    m = client.get("/api/meta").json()
    assert m["model"]["metrics"]["auc_roc"] > 0.7 and len(m["rules"]) >= 8


def test_score_shape_and_monotonicity(client):
    r = client.post("/api/score", json=GOOD).json()
    assert 0 <= r["risk_score"] <= 100 and r["risk_band"] in ("low", "elevated", "high")
    assert len(r["factors"]) == 7 and r["recommendations"]
    worse = client.post("/api/score", json={**GOOD, "geopolitical_risk_index": 95, "weather_risk_level": "high", "reliability_score": 0.55}).json()
    assert worse["risk_score"] >= r["risk_score"]


def test_score_accepts_percent_reliability(client):
    a = client.post("/api/score", json={**GOOD, "reliability_score": 85}).json()
    b = client.post("/api/score", json=GOOD).json()
    assert a["risk_score"] == b["risk_score"]


def test_score_rejects_bad_input_with_field_errors(client):
    r = client.post("/api/score", json={**GOOD, "lead_time_days": "soon", "weather_risk_level": "stormy", "reliability_score": 170})
    assert r.status_code == 422
    fields = {e["field"] for e in r.json()["detail"]["errors"]}
    assert fields == {"lead_time_days", "weather_risk_level", "reliability_score"}


def test_supplier_crud_roundtrip(client):
    n0 = len(client.get("/api/suppliers").json())
    created = client.post("/api/suppliers", json={**GOOD, "average_cost_per_unit": 10, "annual_volume_units": 1000})
    assert created.status_code == 201
    sid = created.json()["supplier_id"]
    assert len(client.get("/api/suppliers").json()) == n0 + 1
    upd = client.put(f"/api/suppliers/{sid}", json={**GOOD, "geopolitical_risk_index": 99, "weather_risk_level": "high"}).json()
    assert upd["risk_score"] >= created.json()["risk_score"]
    detail = client.get(f"/api/suppliers/{sid}").json()
    assert detail["record"]["geopolitical_risk_index"] == 99 and detail["history"] == []
    assert client.delete(f"/api/suppliers/{sid}").status_code == 200
    assert client.delete(f"/api/suppliers/{sid}").status_code == 404
    assert client.put("/api/suppliers/NOPE", json=GOOD).status_code == 404


def test_csv_upload_partial_validity(client):
    csv = ("Supplier,Lead Time (days),Reliability,Geopolitical Risk,Weather,extra\n"
           "Alpha,30,0.9,20,low,x\n"
           "Beta,abc,0.9,20,low,x\n"
           "Gamma,30,0.9,20,foggy,x\n"
           ",30,0.9,20,low,x\n")
    r = client.post("/api/score/csv", files={"file": ("s.csv", csv.encode(), "text/csv")}).json()
    assert r["rows_total"] == 4 and r["rows_scored"] == 1
    assert {(e["row"], e["field"]) for e in r["errors"]} == {(3, "lead_time_days"), (4, "weather_risk_level"), (5, "supplier_name")}
    assert any("extra" in w for w in r["warnings"])


def test_csv_missing_columns_and_bad_files(client):
    r = client.post("/api/score/csv", files={"file": ("s.csv", b"name,foo\nA,1\n", "text/csv")}).json()
    assert r["rows_scored"] == 0 and "Missing required" in r["errors"][0]["message"]
    assert client.post("/api/score/csv", files={"file": ("s.xlsx", b"zz", "application/octet-stream")}).status_code == 400
    r = client.post("/api/score/csv", files={"file": ("empty.csv", b"supplier_name,lead_time_days,reliability_score,geopolitical_risk_index,weather_risk_level\n", "text/csv")}).json()
    assert r["rows_scored"] == 0 and "no rows" in r["errors"][0]["message"]


def test_template_roundtrips_and_export(client):
    t = client.get("/api/template.csv")
    r = client.post("/api/score/csv", files={"file": ("t.csv", t.content, "text/csv")}).json()
    assert r["rows_scored"] == 3 and not r["errors"]
    e = client.get("/api/export.csv")
    assert e.status_code == 200 and e.text.startswith("supplier_id,")
