# ADR-001: Authentication Standard

## Status: Accepted

## Decision
All services must use OAuth 2.1 with PKCE for authentication.
JWT tokens are the only accepted format for session management.
Tokens must expire within 1 hour. Refresh tokens must be rotated on every use.

## Rationale
Legacy session-based auth caused security incidents in Q2 2024.
OAuth 2.1 with PKCE eliminates the implicit flow vulnerabilities we were exposed to.

## Consequences
- Any service still using basic auth or API keys for user-facing endpoints is non-compliant
- All new services must implement the shared auth library at /libs/auth
- Services using custom JWT implementations without the shared library are violations