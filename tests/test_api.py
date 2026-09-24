import pytest
from fastapi.testclient import TestClient

from app.main import app
from risklens import store

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(autouse=True)
def fresh_book():
    store.reset()
    yield
    store.reset()


@pytest.fixture
def client():
    return TestClient(app)


GOOD = {"consignment_id": "T-1", "cargo": "Test cargo", "origin_port": "Chennai", "destination_port": "Dubai",
        "lead_time_days": 40, "reliability_score": 0.85, "geopolitical_risk_index": 30, "weather_risk_level": "medium",
        "units": 1000, "average_cost_per_unit": 50}


def test_overview_is_scoped_to_one_company(client):
    o = client.get("/api/overview").json()
    s = o["summary"]
    assert s["n"] == 7 and s["in_transit"] + s["scheduled"] <= 7
    assert {r["consignment_id"] for r in o["consignments"]} == {f"CN-26-09{n}" for n in (11, 14, 17, 20, 22, 25, 28)}
    for r in o["consignments"]:
        assert r["origin_port"] and r["destination_port"] and r["journey"] and len(r["trend"]) == 30
    lanes = {f'{r["origin_port"]} → {r["destination_port"]}' for r in o["consignments"]}
    assert all(d["lane"] in lanes for d in o["recent_disruptions"])
    m = client.get("/api/meta").json()
    assert m["company"]["name"] and len(m["features"]) == 7


def test_score_shape_alternatives_and_monotonicity(client):
    r = client.post("/api/score", json=GOOD).json()
    assert 0 <= r["risk_score"] <= 100 and r["risk_band"] in ("low", "elevated", "high")
    assert len(r["factors"]) == 7 and r["recommendations"] and r["alternatives"]
    for a in r["alternatives"]:
        assert a["net_benefit_usd"] == a["loss_avoided_usd"] - a["cost_usd"]
    worse = client.post("/api/score", json={**GOOD, "geopolitical_risk_index": 95, "weather_risk_level": "high", "reliability_score": 0.55}).json()
    assert worse["risk_score"] >= r["risk_score"]


def test_curated_alternatives_and_apply(client):
    d = client.get("/api/consignments/CN-26-0917").json()
    assert [a["id"] for a in d["alternatives"]] and d["history"]
    best = d["best_alternative"]
    assert best and best["risk_score"] < d["risk_score"]
    applied = client.post(f"/api/consignments/CN-26-0917/apply/{best['id']}").json()
    assert applied["risk_score"] == pytest.approx(best["risk_score"], abs=0.2)
    assert applied["applied_alternative"] == best["id"]
    assert best["id"] not in [a["id"] for a in applied["alternatives"]]
    assert client.post("/api/consignments/CN-26-0917/apply/NOPE").status_code == 404


def test_score_accepts_percent_reliability(client):
    a = client.post("/api/score", json={**GOOD, "reliability_score": 85}).json()
    b = client.post("/api/score", json=GOOD).json()
    assert a["risk_score"] == b["risk_score"]


def test_score_rejects_bad_input_with_field_errors(client):
    r = client.post("/api/score", json={**GOOD, "lead_time_days": "soon", "weather_risk_level": "stormy", "reliability_score": 170, "eta_date": "next week"})
    assert r.status_code == 422
    fields = {e["field"] for e in r.json()["detail"]["errors"]}
    assert fields == {"lead_time_days", "weather_risk_level", "reliability_score", "eta_date"}
    r = client.post("/api/score", json={**GOOD, "dispatch_date": "2026-10-10", "eta_date": "2026-10-01"})
    assert r.status_code == 422 and r.json()["detail"]["errors"][0]["field"] == "eta_date"


def test_consignment_crud_roundtrip(client):
    no_id = {k: v for k, v in GOOD.items() if k != "consignment_id"}
    created = client.post("/api/consignments", json=no_id)
    assert created.status_code == 201
    cid = created.json()["consignment_id"]
    assert cid.startswith("CN-") and cid != "T-1"  # server assigns the ID
    assert len(client.get("/api/consignments").json()) == 8
    upd = client.put(f"/api/consignments/{cid}", json={**GOOD, "geopolitical_risk_index": 99, "weather_risk_level": "high"}).json()
    assert upd["risk_score"] >= created.json()["risk_score"]
    detail = client.get(f"/api/consignments/{cid}").json()
    assert detail["record"]["geopolitical_risk_index"] == 99 and detail["history"] == []
    assert client.delete(f"/api/consignments/{cid}").status_code == 200
    assert client.delete(f"/api/consignments/{cid}").status_code == 404
    assert client.put("/api/consignments/NOPE", json=GOOD).status_code == 404


def test_csv_upload_partial_validity(client):
    csv = ("Shipment ID,From,To,Lead Time (days),Reliability,Geopolitical Risk,Weather,extra\n"
           "A-1,Chennai,Dubai,30,0.9,20,low,x\n"
           "A-2,Chennai,Dubai,abc,0.9,20,low,x\n"
           "A-3,Chennai,Dubai,30,0.9,20,foggy,x\n"
           ",Chennai,Dubai,30,0.9,20,low,x\n")
    r = client.post("/api/score/csv", files={"file": ("s.csv", csv.encode(), "text/csv")}).json()
    assert r["rows_total"] == 4 and r["rows_scored"] == 1
    assert {(e["row"], e["field"]) for e in r["errors"]} == {(3, "lead_time_days"), (4, "weather_risk_level"), (5, "consignment_id")}
    assert r["results"][0]["origin_port"] == "Chennai"
    assert any("extra" in w for w in r["warnings"])


def test_csv_missing_columns_and_bad_files(client):
    r = client.post("/api/score/csv", files={"file": ("s.csv", b"name,foo\nA,1\n", "text/csv")}).json()
    assert r["rows_scored"] == 0 and "Missing required" in r["errors"][0]["message"]
    assert client.post("/api/score/csv", files={"file": ("s.xlsx", b"zz", "application/octet-stream")}).status_code == 400
    r = client.post("/api/score/csv", files={"file": ("empty.csv", b"consignment_id,lead_time_days,reliability_score,geopolitical_risk_index,weather_risk_level\n", "text/csv")}).json()
    assert r["rows_scored"] == 0 and "no rows" in r["errors"][0]["message"]


def test_template_roundtrips_import_and_export(client):
    t = client.get("/api/template.csv")
    r = client.post("/api/score/csv", files={"file": ("t.csv", t.content, "text/csv")}).json()
    assert r["rows_scored"] == 3 and not r["errors"]
    assert client.post("/api/consignments/import", json={"records": r["records"]}).json()["added"] == 3
    assert client.post("/api/consignments/import", json={"records": r["records"]}).json()["added"] == 0
    e = client.get("/api/export.csv")
    assert e.status_code == 200 and e.text.startswith("consignment_id,") and "recommended_alternative" in e.text.splitlines()[0]


def test_overview_geo_for_globe(client):
    o = client.get("/api/overview").json()
    geo = o["geo"]
    ids = {r["consignment_id"] for r in o["consignments"]}
    assert set(geo["routes"]) == ids and not geo["unmapped"]
    for cid, g in geo["routes"].items():
        assert len(g["points"]) >= 2 and g["origin"]["about"] and g["destination"]["about"]
        assert all(-90 <= la <= 90 and -180 <= lo <= 180 for la, lo in g["points"])
    assert geo["hotspots"] and all(set(h["lanes"]) <= ids for h in geo["hotspots"])
    # an unknown port is reported instead of drawn
    client.post("/api/consignments", json={**GOOD, "origin_port": "Atlantis"})
    assert len(client.get("/api/overview").json()["geo"]["unmapped"]) == 1


def test_cargo_profile(client):
    for cid in ("CN-26-0911", "CN-26-0914", "CN-26-0922"):
        p = client.get(f"/api/consignments/{cid}/cargo").json()["profile"]
        L = p["load"]
        assert L["units"] > 0 and L["gross_t"] >= L["net_t"] > 0 and L["equipment_count"] >= 1
        assert 0 < L["fill_weight"] <= 1 and 0 < L["fill_volume"] <= 1
        assert p["handling"] and p["documents"] and all(s["status"] in ("ok", "watch", "breach") for s in p["sensors"])
    assert client.get("/api/consignments/CN-26-0914/cargo").json()["profile"]["hazard"]["un"] == "UN 2902"
    created = client.post("/api/consignments", json={k: v for k, v in GOOD.items() if k != "consignment_id"}).json()
    g = client.get(f"/api/consignments/{created['consignment_id']}/cargo").json()["profile"]
    assert g.get("generic") and g["load"]["units"] == 1000
    assert client.get("/api/consignments/NOPE/cargo").status_code == 404
