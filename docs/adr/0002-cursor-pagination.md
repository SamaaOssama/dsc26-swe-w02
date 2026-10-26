# ADR 0002: Use Cursor-Based Parcel Pagination

## Status

Accepted

## Context

The parcel list must preserve creation order and support filtering by state. A parcel can change state between two page requests, so offset pagination can skip or repeat matching parcels when the filtered list changes.

## Decision

Use cursor-based pagination. The API issues an opaque cursor associated with the last parcel in the current page. It validates incoming cursors and resumes after that parcel's position in the original creation order.

## Consequences

Pagination can continue correctly when earlier parcels change state, and clients do not need to understand the cursor's internal meaning. The application must maintain creation order and track issued cursors, which adds some in-memory state and requires a policy for cursor lifetime and storage growth.
