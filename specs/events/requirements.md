# Events Requirements

## Summary

An events capability: admins create/manage events and see who registered; students discover events in
chat and enroll by giving their **name** (no email), getting a localized `.ics` calendar file. The
events agent is an orchestrator tool (like FAQ-RAG): it lists available events (so it holds their ids),
confirms before enrolling, persists an `Enrollment(session_id, event_id, name, timestamp)`, and returns
a valid `.ics`. Includes an admin frontend section (create/list/delete events + view per-event
registrants).

## Persona & job-to-be-done

As a student, I want to find upcoming events and enroll by just giving my name, so I get a calendar
invite. As an admin, I want to create/manage events and see who's registered for each, so I can run them.

## In / Out of scope

In scope: `Event` model (title/description/start/end/location/timezone) + admin-token CRUD; `Enrollment`
(session_id, event_id, name, timestamp) + admin view of per-event registrants; the events agent as an
orchestrator tool (list events → confirm → enroll(event_id, name) → `.ics`); `.ics` generation via the
`ics` library, localized to the detected timezone with summary/description in `active_lang`; an admin
frontend section (create/list/delete events + view registrants); anonymous student enrollment by name.

Out of scope (own specs / deferred): email/SMTP delivery (name-only, no email); payment; recurring
events; external calendar sync beyond `.ics`; the FAQ-RAG/guardrails/eval features.

## Config flags & values

- `events_enabled` (flag, default **on**): off = the events tool is not registered (debugging).

## User Stories

- As a student, I want to see events and enroll with just my name, so I get a `.ics` invite.
- As an admin, I want to create/delete events behind my token, so the catalog stays current.
- As an admin, I want to see who registered for an event, so I can plan it.

## Acceptance Criteria

1. WHERE the request carries a valid admin token THE SYSTEM SHALL create an event with title, description, start, end, location, and timezone.   <!-- eval: events-001 -->
2. IF an event-management or registrant-view request lacks a valid admin token THEN THE SYSTEM SHALL reject it (401/403) AND not mutate or disclose data.   <!-- eval: events-002 -->
3. WHEN an admin lists events THE SYSTEM SHALL return each event's id, title, start, and end.   <!-- eval: events-003 -->
4. WHEN an admin deletes an event THE SYSTEM SHALL remove it and its enrollments.   <!-- eval: events-004 -->
5. WHEN an admin views an event's registrants THE SYSTEM SHALL return the enrolled names and timestamps for that event.   <!-- eval: events-005 -->
6. THE SYSTEM SHALL provide an admin frontend section to create, list, and delete events and to view per-event registrants, gated by the admin token.   <!-- eval: events-006 -->
7. WHEN a user asks about events THE SYSTEM SHALL list the available events (with their ids held by the agent) via an orchestrator tool.   <!-- eval: events-007 -->
8. WHEN a user wants to enroll THE SYSTEM SHALL ask for the user's name and which event, and the enroll tool SHALL receive the resolved `event_id` and `name`.   <!-- eval: events-008 -->
9. WHEN a user requests enrollment THE SYSTEM SHALL confirm the event and name with the user BEFORE persisting the enrollment.   <!-- eval: events-009 -->
10. WHEN the user confirms THE SYSTEM SHALL persist an `Enrollment(session_id, event_id, name, timestamp)` AND return a `.ics` calendar file for the event.   <!-- eval: events-010 -->
11. THE SYSTEM SHALL localize the `.ics` event times to the detected timezone (geo-fusion) AND write the `.ics` summary/description in the session `active_lang`.   <!-- eval: events-011 -->
12. THE SYSTEM SHALL generate a valid RFC-5545 `.ics` using the `ics` library.   <!-- eval: events-012 -->
13. IF the requested event does not exist THEN THE SYSTEM SHALL NOT enroll AND SHALL tell the user it is unavailable (no invented event).   <!-- eval: events-013 -->
14. THE SYSTEM SHALL run the events agent as an orchestrator tool, forwarding `deps` and `usage` (shared `RunUsage`) and honoring `UsageLimits`.   <!-- eval: events-014 -->
15. THE SYSTEM SHALL conduct the events conversation and `.ics` text in the session `active_lang` (ES/EN/PT); an unsupported language falls back to the configured fallback AND sets `needs_review=true`.   <!-- eval: events-015 -->
16. IF enrollment persistence or `.ics` generation fails THEN THE SYSTEM SHALL degrade to a valid nine-field contract with `needs_review=true` (never a 5xx).   <!-- eval: events-016 -->
17. THE SYSTEM SHALL require only the user's name for enrollment (no email collected).   <!-- eval: events-017 -->
18. WHERE `events_enabled` is false THE SYSTEM SHALL not register the events tool (the agent does not enroll).   <!-- eval: events-018 -->

## Case-id map

`events-001..018` map 1:1 to eval `Case`s of the same id: admin CRUD + auth-reject, registrant view,
list-events, confirm-then-enroll, `.ics` localization, non-existent event, name-only, degraded paths,
and the frontend admin section (events-006, exercised by a frontend/integration check). Ids are
append-only.

## Non-functional / contract

- **Writes** these per-turn contract fields: `reply` (confirmation + enrollment result in `active_lang`),
  `needs_review` (failures / unsupported-language fallback). The `.ics` is returned as a side artifact
  (download), not a contract field. **Reads** the detected timezone (`orchestrator-and-fusion`) and
  `active_lang` (`multilingual`).
- Auth: event CRUD + registrant view require the **admin token**; student enrollment is anonymous,
  identified only by the supplied **name** + `session_id`.
- Languages: the events dialogue + `.ics` text are in **ES / EN / PT** (session `active_lang`);
  unsupported → fallback + `needs_review=true`.
- Enroll is a destructive action: confirm before persisting; the agent passes a resolved `event_id`
  (never invents one). Data: only name + session_id + event_id + timestamp persisted (no email).
- Resilience: enrollment/`.ics` errors degrade to a valid contract with `needs_review=true`, never a 5xx.
