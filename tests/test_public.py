import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.domain import EventType, InvalidTransition, Parcel, ParcelState, apply_event


@pytest.fixture
def client():
    return TestClient(create_app())


def new_parcel(client, ref="ORD-1001", cod=25_000):
    r = client.post("/v1/parcels", json={
        "merchant_ref": ref, "cod_amount_piastres": cod,
        "address_text": "Behind the mosque near the bakery, Faisal, Giza",
    })
    assert r.status_code == 201, r.text
    return r.json()


def test_dispatch_then_deliver():
    p = Parcel(id="pcl_x", merchant_ref="ORD-1", cod_amount_piastres=0, address_text="Nasr City")
    p = apply_event(p, EventType.DISPATCH)
    assert (p.state, p.attempts) == (ParcelState.OUT_FOR_DELIVERY, 1)
    p = apply_event(p, EventType.DELIVER)
    assert p.state == ParcelState.DELIVERED


def test_delivered_parcel_cannot_fail():
    p = Parcel(id="pcl_x", merchant_ref="ORD-1", cod_amount_piastres=0,
               address_text="Nasr City", state=ParcelState.DELIVERED, attempts=1)
    with pytest.raises(InvalidTransition):
        apply_event(p, EventType.FAIL)


def test_create_returns_201_and_location(client):
    body = new_parcel(client)
    assert body["id"].startswith("pcl_")
    assert body["state"] == "created" and body["attempts"] == 0
    r = client.get(f"/v1/parcels/{body['id']}")
    assert r.status_code == 200 and r.json() == body


def test_unknown_parcel_is_a_problem_document(client):
    r = client.get("/v1/parcels/pcl_does_not_exist")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert {"type", "title", "status"} <= r.json().keys()


def test_invalid_transition_is_409(client):
    p = new_parcel(client)
    r = client.post(f"/v1/parcels/{p['id']}/events", json={"type": "deliver"})
    assert r.status_code == 409
    assert r.json()["status"] == 409

def test_list_parcels_paginates_in_creation_order(client):
    first = new_parcel(client, ref="ORD-1")
    second = new_parcel(client, ref="ORD-2")
    third = new_parcel(client, ref="ORD-3")

    page1 = client.get("/v1/parcels?limit=2")
    assert page1.status_code == 200
    body1 = page1.json()

    assert [item["id"] for item in body1["items"]] == [
        first["id"],
        second["id"],
    ]
    assert body1["next_cursor"] is not None

    page2 = client.get(
        "/v1/parcels",
        params={"limit": 2, "cursor": body1["next_cursor"]},
    )
    assert page2.status_code == 200
    body2 = page2.json()

    assert [item["id"] for item in body2["items"]] == [third["id"]]
    assert body2["next_cursor"] is None


def test_list_parcels_rejects_unknown_cursor(client):
    response = client.get(
        "/v1/parcels",
        params={"cursor": "this-is-not-a-valid-cursor"},
    )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith(
        "application/problem+json"
    )


def test_list_parcels_rejects_invalid_limit(client):
    response = client.get("/v1/parcels?limit=101")

    assert response.status_code == 422
    assert response.headers["content-type"].startswith(
        "application/problem+json"
    )

def test_filtered_pagination_survives_state_change(client):
    first = new_parcel(client, ref="ORD-1")
    second = new_parcel(client, ref="ORD-2")
    third = new_parcel(client, ref="ORD-3")

    # Get the first page of parcels in the created state.
    page1 = client.get(
        "/v1/parcels",
        params={"state": "created", "limit": 2},
    )
    assert page1.status_code == 200
    body1 = page1.json()

    assert [item["id"] for item in body1["items"]] == [
        first["id"],
        second["id"],
    ]
    cursor = body1["next_cursor"]
    assert cursor is not None

    # Change the state of the last parcel on page 1.
    event_response = client.post(
        f"/v1/parcels/{second['id']}/events",
        json={"type": "dispatch"},
    )
    assert event_response.status_code == 200

    # Continue listing created parcels.
    page2 = client.get(
        "/v1/parcels",
        params={
            "state": "created",
            "limit": 2,
            "cursor": cursor,
        },
    )
    assert page2.status_code == 200
    body2 = page2.json()

    assert [item["id"] for item in body2["items"]] == [third["id"]]
    assert body2["next_cursor"] is None
