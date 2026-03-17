# ADR-002: API Design Standard

## Status: Accepted

## Decision
All internal APIs must be REST over HTTPS.
GraphQL is not permitted for internal service-to-service communication.
All endpoints must be versioned with a /v1/, /v2/ prefix.
Response payloads must follow the standard envelope format:
{ "data": {}, "error": null, "meta": { "request_id": "" } }

## Rationale
GraphQL introduced unpredictable query complexity and made rate limiting difficult.
Versioned REST endpoints give us clear deprecation paths.

## Consequences
- Any service exposing unversioned endpoints is non-compliant
- GraphQL endpoints on internal services must be migrated
- All responses not following the envelope format are violations