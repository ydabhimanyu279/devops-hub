# ADR-003: Database Access Standard

## Status: Accepted

## Decision
Services must not connect directly to another service's database.
All cross-service data access must go through the owning service's API.
Raw SQL queries are banned in application code — use the ORM layer only.
All database credentials must be injected via environment variables, never hardcoded.

## Rationale
Direct DB access between services caused a cascade failure in the payments cluster in Q3 2024.
Hardcoded credentials were found in three repos during the Q4 2024 security audit.

## Consequences
- Any service with direct DB connections to another service's database is a critical violation
- Hardcoded credentials anywhere in the codebase trigger an automatic security incident
- Raw SQL strings in application code must be refactored to ORM calls