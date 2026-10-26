# ADR 0001: Keep Parcel Lifecycle Rules in a Pure Domain Module

## Status

Accepted

## Context

The Tawseel parcel lifecycle has several states and events. Some event combinations are allowed, while others must be rejected. If these rules are implemented inside HTTP endpoint functions, they can become duplicated and harder to test independently.

## Decision

Keep the parcel lifecycle rules in `app/domain.py`. The `apply_event` function returns a new immutable `Parcel` when an event is valid and raises `InvalidTransition` when it is invalid. The domain module must not depend on FastAPI, Starlette, Pydantic, or SQLAlchemy.

## Consequences

The lifecycle rules can be tested independently of HTTP requests, and the API can translate domain errors into HTTP responses. The trade-off is that the HTTP layer must handle `InvalidTransition` explicitly and convert it into the appropriate response.
