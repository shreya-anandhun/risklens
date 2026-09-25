import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from risklens import datasets, store
from risklens.book import BOOK_PATH

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(autouse=True)
def fresh_book():
    store.reset()
    yield
    store.reset()


@pytest.fixture
def client():
    return TestClient(app)


GOOD = {"consignment_id": "T-1", "cargo": "Test cargo", "product_category": "Electronics", "mode": "Sea",
        "origin_port": "Shanghai", "destination_port": "Rotterdam", "weight_t": 120, "reliability_score": 0.85,
        "geopolitical_risk_index": 30, "weather_condition": "Rain", "fuel_price_index": 2.5, "distance_km": 18000}


def test_book_is_real_dataset_shipments(client):
    o = client.get("/api/overview").json()
    book = pd.read_csv(BOOK_PATH)
    ships = datasets.load()["shipments"].set_index("shipment_id")
    assert o["summary"]["n"] == len(book) >= 8
    for r in o["consignments"]:
        src = ships.loc[r["consignment_id"]]            # every consignment is a row in the Kaggle data
        assert r["origin_port"] == src.origin_port and r["mode"] == src["mode"]
        assert r["inputs"]["reliability_score"] == pytest.approx(src.reliability_score)
        assert r["journey"]["status"] in ("In transit", "Scheduled") and r["trend"]
    assert {r["risk_band"] for r in o["consignments"]} == {"low", "elevated", "high"}
    lanes = {f'{r["origin_port"]} → {r["destination_port"]}' for r in o["consignments"]}
    assert o["recent_disruptions"] and all(d["lane"] in lanes for d in o["recent_disruptions"])
    assert 0 < o["catch_rate"] <= 100 and len(o["sources"]) == 4
    m = client.get("/api/meta").json()
    assert m["model"]["auc_roc"] > 0.7 and len(m["features"]) == 5 and m["as_of"] == "2025-12-20"


def test_score_shape_alternatives_and_monotonicity(client):
    r = client.post("/api/score", json={**GOOD, "weather_condition": "Storm", "geopolitical_risk_index": 70}).json()
    assert 0 <= r["risk_score"] <= 100 and r["risk_band"] in ("low", "elevated", "high")
    assert len(r["factors"]) == 5 and r["recommendations"] and r["alternatives"] and r["context"]["lane"]["shipments"] > 0
    for a in r["alternatives"]:
        assert a["net_benefit_usd"] == a["loss_avoided_usd"] - a["cost_usd"]
    calm = client.post("/api/score", json=GOOD).json()
    worse = client.post("/api/score", json={**GOOD, "geopolitical_risk_index": 95, "weather_condition": "Hurricane", "reliability_score": 0.55}).json()
    assert worse["risk_score"] >= calm["risk_score"]


def test_alternatives_are_rescored_and_apply(client):
    o = client.get("/api/overview").json()
    cid = next(r["consignment_id"] for r in o["consignments"] if r.get("best_alternative"))
    d = client.get(f"/api/consignments/{cid}").json()
    best = d["best_alternative"]
    assert best["risk_score"] < d["risk_score"] and d["history"]
    applied = client.post(f"/api/consignments/{cid}/apply/{best['id']}").json()
    assert applied["risk_score"] == pytest.approx(best["risk_score"], abs=0.2)
    assert applied["applied_alternative"] == best["id"]
    assert best["id"] not in [a["id"] for a in applied["alternatives"]]
    assert client.post(f"/api/consignments/{cid}/apply/NOPE").status_code == 404


def test_score_accepts_percent_reliability_and_kaggle_geo_score(client):
    a = client.post("/api/score", json={**GOOD, "reliability_score": 85}).json()
    b = client.post("/api/score", json=GOOD).json()
    c = client.post("/api/score", json={**{k: v for k, v in GOOD.items() if k != "geopolitical_risk_index"}, "Geopolitical_Risk_Score": 3}).json()
    assert a["risk_score"] == b["risk_score"] == c["risk_score"]


def test_score_rejects_bad_input_with_field_errors(client):
    r = client.post("/api/score", json={**GOOD, "weight_t": "heavy", "weather_condition": "snowy", "reliability_score": 170, "eta_date": "next week"})
    assert r.status_code == 422
    fields = {e["field"] for e in r.json()["detail"]["errors"]}
    assert fields == {"weight_t", "weather_condition", "reliability_score", "eta_date"}
    r = client.post("/api/score", json={**GOOD, "dispatch_date": "2025-12-10", "eta_date": "2025-12-01"})
    assert r.status_code == 422 and r.json()["detail"]["errors"][0]["field"] == "eta_date"


def test_consignment_crud_roundtrip(client):
    n = len(client.get("/api/consignments").json())
    no_id = {k: v for k, v in GOOD.items() if k != "consignment_id"}
    created = client.post("/api/consignments", json=no_id)
    assert created.status_code == 201
    cid = created.json()["consignment_id"]
    assert cid.startswith("CN-") and cid != "T-1"  # server assigns the ID
    assert len(client.get("/api/consignments").json()) == n + 1
    upd = client.put(f"/api/consignments/{cid}", json={**GOOD, "geopolitical_risk_index": 99, "weather_condition": "Hurricane"}).json()
    assert upd["risk_score"] >= created.json()["risk_score"]
    detail = client.get(f"/api/consignments/{cid}").json()
    assert detail["record"]["geopolitical_risk_index"] == 99 and detail["history"]
    assert client.delete(f"/api/consignments/{cid}").status_code == 200
    assert client.delete(f"/api/consignments/{cid}").status_code == 404
    assert client.put("/api/consignments/NOPE", json=GOOD).status_code == 404


def test_csv_upload_partial_validity(client):
    csv = ("Shipment ID,From,To,Carrier Reliability,Geopolitical Risk,Weather,extra\n"
           "A-1,Shanghai,Busan,0.9,20,Clear,x\n"
           "A-2,Shanghai,Busan,abc,20,Clear,x\n"
           "A-3,Shanghai,Busan,0.9,20,Snow,x\n"
           ",Shanghai,Busan,0.9,20,Clear,x\n")
    r = client.post("/api/score/csv", files={"file": ("s.csv", csv.encode(), "text/csv")}).json()
    assert r["rows_total"] == 4 and r["rows_scored"] == 1
    assert {(e["row"], e["field"]) for e in r["errors"]} == {(3, "reliability_score"), (4, "weather_condition"), (5, "consignment_id")}
    assert r["results"][0]["origin_port"] == "Shanghai" and r["outcome"] is None
    assert any("extra" in w for w in r["warnings"])


def test_kaggle_file_scores_and_checks_against_outcomes(client):
    path = datasets.RAW["shipments"]
    if not path.exists():
        pytest.skip("raw Kaggle file not downloaded")
    r = client.post("/api/score/csv", files={"file": (path.name, path.read_bytes(), "text/csv")}).json()
    assert r["rows_scored"] == 5000 and not r["errors"] and not r["warnings"]
    assert r["outcome"]["rows"] == 5000 and r["outcome"]["agreement"] > 0.65 and r["outcome"]["caught"] > 0.8


def test_csv_missing_columns_and_bad_files(client):
    r = client.post("/api/score/csv", files={"file": ("s.csv", b"name,foo\nA,1\n", "text/csv")}).json()
    assert r["rows_scored"] == 0 and "Missing required" in r["errors"][0]["message"]
    assert client.post("/api/score/csv", files={"file": ("s.xlsx", b"zz", "application/octet-stream")}).status_code == 400
    r = client.post("/api/score/csv", files={"file": ("empty.csv", b"Shipment_ID,Carrier_Reliability_Score,Geopolitical_Risk_Score,Weather_Condition\n", "text/csv")}).json()
    assert r["rows_scored"] == 0 and "no rows" in r["errors"][0]["message"]


def test_template_roundtrips_import_and_export(client):
    t = client.get("/api/template.csv")
    assert t.text.startswith("Shipment_ID,Date,Origin_Port")
    r = client.post("/api/score/csv", files={"file": ("t.csv", t.content, "text/csv")}).json()
    assert r["rows_scored"] == 5 and not r["errors"]
    added = client.post("/api/consignments/import", json={"records": r["records"]}).json()["added"]
    assert added >= 1
    assert client.post("/api/consignments/import", json={"records": r["records"]}).json()["added"] == 0
    e = client.get("/api/export.csv")
    head = e.text.splitlines()[0].split(",")
    assert e.status_code == 200 and head[0] == "Shipment_ID"
    assert {"Route", "Journey", "Trend_30d", "Risk_Level", "Best_Alternative", "Alternative_Risk_Score"} <= set(head)


def test_export_uploads_back_into_what_if(client):
    e = client.get("/api/export.csv")
    df = pd.read_csv(__import__("io").BytesIO(e.content))
    assert all(len(t.split()) == 30 for t in df.Trend_30d)
    r = client.post("/api/score/csv", files={"file": ("export.csv", e.content, "text/csv")}).json()
    assert r["rows_scored"] == len(df) and not r["errors"] and not r["warnings"]
    back = {x["consignment_id"]: x["risk_score"] for x in r["results"]}
    assert all(back[s] == pytest.approx(sc, abs=0.2) for s, sc in zip(df.Shipment_ID, df.Risk_Score))


def test_overview_geo_for_globe(client):
    o = client.get("/api/overview").json()
    geo = o["geo"]
    ids = {r["consignment_id"] for r in o["consignments"]}
    assert set(geo["routes"]) == ids and not geo["unmapped"]
    for cid, g in geo["routes"].items():
        assert len(g["points"]) >= 2 and g["origin"]["about"] and g["destination"]["about"]
        assert all(-90 <= la <= 90 and -180 <= lo <= 180 for la, lo in g["points"])
    assert geo["hotspots"] and all(set(h["lanes"]) <= ids for h in geo["hotspots"])
    assert any(h["gpr"] for h in geo["hotspots"])        # real GPR readings on the chokepoints
    # an unknown port is reported instead of drawn
    client.post("/api/consignments", json={**GOOD, "origin_port": "Atlantis"})
    assert len(client.get("/api/overview").json()["geo"]["unmapped"]) == 1


def test_sea_routes_pass_the_real_chokepoints():
    from risklens.geo import NODES, sea_path
    names = lambda o, d: {k for p in sea_path(o, d) for k, v in NODES.items() if v == p}
    assert {"malacca", "bab_el_mandeb", "suez"} <= names("Shanghai", "Rotterdam")
    assert "panama" in names("Los Angeles", "Hamburg") and "hormuz" in names("Singapore", "Dubai")


def test_cargo_profile(client):
    o = client.get("/api/overview").json()
    for r in o["consignments"]:
        p = client.get(f"/api/consignments/{r['consignment_id']}/cargo").json()["profile"]
        L = p["load"]
        assert L["units"] > 0 and L["gross_t"] >= L["net_t"] > 0 and L["equipment_count"] >= 1
        assert 0 < L["fill_weight"] <= 1 and 0 < L["fill_volume"] <= 1
        assert p["handling"] and p["documents"] and all(s["status"] in ("ok", "watch", "breach") for s in p["sensors"])
    created = client.post("/api/consignments", json={k: v for k, v in GOOD.items() if k != "consignment_id"}).json()
    g = client.get(f"/api/consignments/{created['consignment_id']}/cargo").json()["profile"]
    assert g["hazard"]["un"] == "UN 3481" and g["load"]["net_t"] == pytest.approx(120)
    assert client.get("/api/consignments/NOPE/cargo").status_code == 404


def test_warehouse_notifications_and_impact(client):
    from risklens import notify
    notify.clear()
    acts = client.get("/api/overview").json()["top_actions"]
    a = acts[0]
    imp = a["impact"]
    assert imp["risk_after"] < imp["risk_before"] and imp["loss_after"] < imp["loss_before"] and imp["effects"]
    assert a["notified"] is None
    d = client.get(f"/api/actions/{a['consignment_id']}/{a['id']}/draft").json()
    assert d["recipients"] and a["consignment_id"] in d["subject"]
    assert all(r["email"].endswith("@northwind.example.com") for r in d["recipients"])
    sent = client.post("/api/notifications", json={"consignment_id": a["consignment_id"], "action_id": a["id"],
                                                    "recipients": [d["recipients"][0]["key"]]})
    assert sent.status_code == 201 and len(sent.json()["recipients"]) == 1 and "demo" in sent.json()["status"]
    again = [x for x in client.get("/api/overview").json()["top_actions"] if x["consignment_id"] == a["consignment_id"] and x["id"] == a["id"]][0]
    assert again["notified"]["id"] == sent.json()["id"]
    assert len(client.get("/api/notifications").json()) == 1
    assert client.post("/api/notifications", json={"consignment_id": a["consignment_id"], "action_id": "nope"}).status_code == 404
    assert client.post("/api/notifications", json={"consignment_id": a["consignment_id"], "action_id": a["id"], "recipients": ["zzz"]}).status_code == 422
    client.post("/api/consignments/reset")
    assert client.get("/api/notifications").json() == []


def test_serving_does_not_need_scikit_learn():
    # scikit-learn is a training-only dependency; the deployed app does not install it.
    import subprocess, sys
    code = (
        "import sys, importlib.abc\n"
        "class Hide(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, name, path, target=None):\n"
        "        if name == 'sklearn' or name.startswith('sklearn.'): raise ImportError(name)\n"
        "sys.meta_path.insert(0, Hide())\n"
        "from fastapi.testclient import TestClient\n"
        "from app.main import app\n"
        "c = TestClient(app)\n"
        "for p in ('/api/meta', '/api/overview'): assert c.get(p).status_code == 200, p\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]


def test_sample_new_consignments_add_ten_to_the_board(client):
    from pathlib import Path
    raw = (Path(__file__).resolve().parent.parent / "data" / "samples" / "new_consignments.csv").read_bytes()
    r = client.post("/api/score/csv", files={"file": ("new.csv", raw, "text/csv")}).json()
    assert r["rows_scored"] == 10 and not r["errors"] and not r["warnings"]
    n = len(client.get("/api/consignments").json())
    assert client.post("/api/consignments/import", json={"records": r["records"]}).json()["added"] == 10
    o = client.get("/api/overview").json()
    assert o["summary"]["n"] == n + 10 and all(x["journey"] and x["trend"] for x in o["consignments"])
