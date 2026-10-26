"""HTTP layer for the Tawseel parcel service.

The HTTP layer translates requests into calls to app.domain; the domain decides.
See README.md for the four operations, their operationIds and their errors.
"""
import base64
import secrets
from uuid import uuid4

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.domain import (
    EventType,
    InvalidTransition,
    Parcel,
    ParcelState,
    apply_event,
)


class CreateParcelRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    merchant_ref: str = Field(min_length=1, max_length=64)
    cod_amount_piastres: int = Field(ge=0, le=5_000_000)
    address_text: str = Field(min_length=1, max_length=500)



class ParcelEventRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    type: str = Field(min_length=1)



def problem_response(status_code: int, title: str, errors=None):
    body = {
        "type": "about:blank",
        "title": title,
        "status": status_code,
    }
    if errors is not None:
        body["errors"] = errors

    return JSONResponse(
        status_code=status_code,
        content=body,
        media_type="application/problem+json",
    )


def validation_errors(exc: RequestValidationError):
    errors = []
    seen = set()

    for error in exc.errors():
        loc = error["loc"]
        field = tuple(loc)

        if field in seen:
            continue

        seen.add(field)
        errors.append({
            "loc": list(loc),
            "msg": error["msg"],
        })

    return errors


def create_app() -> FastAPI:
    app = FastAPI()
    app.state.parcels = {}
    app.state.parcel_order = []
    app.state.valid_cursors = {}

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ):
        return problem_response(
            422,
            "Unprocessable Entity",
            validation_errors(exc),
        )

    @app.post(
        "/v1/parcels",
        status_code=201,
        operation_id="createParcel",
        responses={
            409: {"description": "Duplicate merchant reference"},
            422: {"description": "Invalid request body"},
        },
    )
    def create_parcel(data: CreateParcelRequest, request: Request):
        parcels = request.app.state.parcels

        if any(
            parcel.merchant_ref == data.merchant_ref
            for parcel in parcels.values()
        ):
            return problem_response(409, "Conflict")

        parcel_id = f"pcl_{uuid4().hex}"

        parcel = Parcel(
            id=parcel_id,
            merchant_ref=data.merchant_ref,
            cod_amount_piastres=data.cod_amount_piastres,
            address_text=data.address_text,
        )

        parcels[parcel.id] = parcel
        request.app.state.parcel_order.append(parcel.id)

        return JSONResponse(
            status_code=201,
            content={
                "id": parcel.id,
                "merchant_ref": parcel.merchant_ref,
                "cod_amount_piastres": parcel.cod_amount_piastres,
                "address_text": parcel.address_text,
                "state": parcel.state.value,
                "attempts": parcel.attempts,
            },
            headers={"Location": f"/v1/parcels/{parcel.id}"},
        )

    @app.get(
        "/v1/parcels/{parcel_id}",
        operation_id="getParcel",
        responses={404: {"description": "Parcel not found"}},
    )
    def get_parcel(parcel_id: str, request: Request):
        parcels = request.app.state.parcels

        parcel = parcels.get(parcel_id)

        if parcel is None:
            return problem_response(404, "Not Found")

        return {
            "id": parcel.id,
            "merchant_ref": parcel.merchant_ref,
            "cod_amount_piastres": parcel.cod_amount_piastres,
            "address_text": parcel.address_text,
            "state": parcel.state.value,
            "attempts": parcel.attempts,
        }

    @app.post(
        "/v1/parcels/{parcel_id}/events",
        operation_id="recordParcelEvent",
        responses={
            404: {"description": "Parcel not found"},
            409: {"description": "Invalid state transition"},
            422: {"description": "Invalid event request"},
        },
    )
    def record_parcel_event(
        parcel_id: str,
        data: ParcelEventRequest,
        request: Request,
    ):
        parcels = request.app.state.parcels
        parcel = parcels.get(parcel_id)

        # Check whether the parcel exists
        if parcel is None:
            return problem_response(404, "Not Found")

        # Convert the event string to EventType
        try:
            event = EventType(data.type)
        except ValueError:
            return problem_response(
                422,
                "Unprocessable Entity",
                [{"loc": ["body", "type"], "msg": "Unknown event type"}],
            )

        # Apply the event to the parcel
        try:
            updated_parcel = apply_event(parcel, event)
        except InvalidTransition:
            return problem_response(409, "Conflict")

        # Save the updated parcel only if the transition is valid
        parcels[parcel_id] = updated_parcel

        return {
            "id": updated_parcel.id,
            "merchant_ref": updated_parcel.merchant_ref,
            "cod_amount_piastres": updated_parcel.cod_amount_piastres,
            "address_text": updated_parcel.address_text,
            "state": updated_parcel.state.value,
            "attempts": updated_parcel.attempts,
        }

    @app.get(
        "/v1/parcels",
        operation_id="listParcels",
        responses={
            400: {"description": "Invalid cursor"},
            422: {"description": "Invalid state or limit"},
        },
    )

    def list_parcels(
        request: Request,
        state: ParcelState | None = None,
        limit: int = Query(default=20, ge=1, le=100),
        cursor: str | None = None,
    ):
        parcels = request.app.state.parcels
        parcel_order = request.app.state.parcel_order
        valid_cursors = request.app.state.valid_cursors

        # Accept only cursors issued by this app.
        start_after = None
        if cursor is not None:
            if cursor not in valid_cursors:
                return problem_response(400, "Bad Request")

            start_after = valid_cursors[cursor]

        # Keep creation order and apply the optional state filter.
        matching_ids = [
            parcel_id
            for parcel_id in parcel_order
            if state is None or parcels[parcel_id].state == state
        ]

        # Resume after the last parcel of the previous page.
        if start_after is not None:
            try:
                original_position = parcel_order.index(start_after)
            except ValueError:
                return problem_response(400, "Bad Request")

            matching_ids = [
                parcel_id
                for parcel_id in matching_ids
                if parcel_order.index(parcel_id) > original_position
            ]

        # Select the current page.
        page_ids = matching_ids[:limit]

        items = []
        for parcel_id in page_ids:
            parcel = parcels[parcel_id]
            items.append({
                "id": parcel.id,
                "merchant_ref": parcel.merchant_ref,
                "cod_amount_piastres": parcel.cod_amount_piastres,
                "address_text": parcel.address_text,
                "state": parcel.state.value,
                "attempts": parcel.attempts,
            })

        # Issue a cursor only when another page exists.
        next_cursor = None
        if len(matching_ids) > limit and page_ids:
            next_cursor = secrets.token_urlsafe(32)
            valid_cursors[next_cursor] = page_ids[-1]

        return {
            "items": items,
            "next_cursor": next_cursor,
        }

    return app





# `uvicorn app.api:app` needs a module-level app. Once create_app() works,
# replace the line below with:  app = create_app()
app = create_app()
