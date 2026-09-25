import pytest
from fastapi.testclient import TestClient

from app.main import app
from risklens import store, workflow

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(autouse=True)
def fresh():
    store.reset(); workflow.clear()
    yield
    store.reset(); workflow.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _action(client, ids):
    acts = client.get("/api/overview").json()["top_actions"]
    return next(a for a in acts if a["id"] in ids)


def _run(client, w):
    while w["status"] != "done":
        w = client.post(f"/api/workflows/{w['id']}/advance").json()
    return w


def test_plan_is_grounded_in_the_consignment(client):
    a = _action(client, {"weather_window", "geo_reroute", "carrier_switch"})
    w = client.post("/api/workflows", json={"consignment_id": a["consignment_id"], "action_id": a["id"]}).json()
    assert w["status"] == "running" and w["revealed"] == 1 and w["steps"]["deploy"] is None
    S = w["steps"]
    assert len(S["questions"]) == len(S["answers"]) >= 5 and all(x["source"] for x in S["answers"])
    assert a["consignment_id"] in S["mail"]["subject"] and S["mail"]["to"]["email"].endswith("@northwind.example.com")
    detail = client.get(f"/api/consignments/{a['consignment_id']}").json()
    assert f"{detail['risk_score']:.0f}" in S["answers"][-2]["a"]        # the risk quoted is the model's score
    assert S["reply"]["simulated"] and S["understand"]["decision"] == "approve"
    kinds = {g["kind"] for g in S["reply"]["segments"]}
    assert {"decision", "date", "constraint"} <= kinds


def test_deploy_applies_the_alternative_and_rescores(client):
    a = _action(client, {"weather_window", "geo_reroute", "carrier_switch"})
    before = client.get(f"/api/consignments/{a['consignment_id']}").json()["risk_score"]
    w = client.post("/api/workflows", json={"consignment_id": a["consignment_id"], "action_id": a["id"]}).json()
    steps = []
    while w["status"] != "done":
        w = client.post(f"/api/workflows/{w['id']}/advance").json()
        steps.append(w["revealed"])
    assert steps == [2, 3, 4, 5, 6, 7]
    d = w["steps"]["deploy"]
    assert d["kind"] == "alternative" and d["rescored"] and d["risk_after"] < d["risk_before"] == pytest.approx(before, abs=0.1)
    after = client.get(f"/api/consignments/{a['consignment_id']}").json()
    assert after["risk_score"] == pytest.approx(d["risk_after"], abs=0.1)
    assert after["record"]["applied_alternative"] and a["id"] in after["record"]["executed_actions"]
    assert client.get("/api/overview").json()["workflows_done"] == 1
    assert client.post(f"/api/workflows/{w['id']}/advance").json()["status"] == "done"   # idempotent once done


def test_deploy_records_other_actions_and_shifts_eta(client):
    a = _action(client, {"schedule_buffer"})
    eta = client.get(f"/api/consignments/{a['consignment_id']}").json()["journey"]["eta_date"]
    w = _run(client, client.post("/api/workflows", json={"consignment_id": a["consignment_id"], "action_id": a["id"]}).json())
    d = w["steps"]["deploy"]
    assert d["kind"] == "recorded" and d["eta_after"] > eta
    acts = client.get("/api/overview").json()["top_actions"]
    mine = next(x for x in acts if x["consignment_id"] == a["consignment_id"] and x["id"] == a["id"])
    assert mine["executed"] and mine["deployed"]["id"] == w["id"]


def test_workflow_errors_and_reset(client):
    assert client.post("/api/workflows", json={"consignment_id": "NOPE", "action_id": "weather_window"}).status_code == 404
    a = _action(client, {"weather_window", "geo_reroute", "carrier_switch", "schedule_buffer"})
    assert client.post("/api/workflows", json={"consignment_id": a["consignment_id"], "action_id": "nope"}).status_code == 404
    assert client.post("/api/workflows/WF-NOPE/advance").status_code == 404
    w = _run(client, client.post("/api/workflows", json={"consignment_id": a["consignment_id"], "action_id": a["id"]}).json())
    assert client.get(f"/api/workflows/{w['id']}").json()["status"] == "done" and len(client.get("/api/workflows").json()) == 1
    client.post("/api/consignments/reset")
    assert client.get("/api/workflows").json() == []
