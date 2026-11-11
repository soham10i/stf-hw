---
title: "Error codes"
scope: "Every failure of the API answers with one JSON body: HTTP routes, the event streams (POST /chat/stream, POST /chat/tts/stream: an error event) and the sockets (a type: \"error\" message)."
module: architecture
last_verified: 2026-11-09
---

# Error codes

Every failure of the API answers with one JSON body: HTTP routes, the event streams
(`POST /chat/stream`, `POST /chat/tts/stream`: an `error` event) and the sockets (a `type: "error"`
message). The codes are defined in `services/api/core/errors.py`; this page is checked against
them by `tests/test_errors.py`.

```json
{
  "code": "rate_limited",
  "reason": "daily_budget_spent",
  "status": 429,
  "message": "today's question budget is used up",
  "request_id": "5f0c9a1e2b7d4c38",
  "error": "today's question budget is used up",
  "detail": "today's question budget is used up"
}
```

| Field | Meaning |
| --- | --- |
| `code` | Universal code, one per HTTP condition. A client that knows only these handles every error. |
| `reason` | Custom code: the situation inside this API. Absent when only the universal code applies. |
| `status` | The HTTP status (also on streams and sockets, which have none of their own). |
| `message` | Safe to show a visitor: never a key, a path or a stack trace. |
| `request_id` | Also in the `X-Request-ID` response header and in every log line of the request. |
| `error`, `detail` | Copies of `message` for clients written before the codes. New code reads `message`. |
| `fields` | Only on `validation_failed`: each invalid field and why. |

A caller may send its own `X-Request-ID` (8 to 64 characters of `A-Z a-z 0-9 . _ -`); otherwise the
server makes one. Quote it when reporting a problem: it finds the request's log lines.

## Universal codes

| Code | Status | Default message |
| --- | --- | --- |
| `bad_request` | 400 | the request is not valid |
| `unauthenticated` | 401 | sign in first |
| `forbidden` | 403 | not allowed |
| `not_found` | 404 | not found |
| `method_not_allowed` | 405 | this method is not served here |
| `conflict` | 409 | the state changed: reload and try again |
| `gone` | 410 | no longer available |
| `payload_too_large` | 413 | the request is too large |
| `unsupported_media_type` | 415 | this content type is not accepted |
| `validation_failed` | 422 | the request's fields are not valid |
| `rate_limited` | 429 | too many requests: wait a few seconds |
| `internal` | 500 | an unexpected error occurred processing your request |
| `upstream_failed` | 502 | a service this depends on failed |
| `unavailable` | 503 | not available on this server right now |
| `upstream_timeout` | 504 | a service this depends on did not answer |

An unlisted status keeps its own number in `status` and takes `bad_request` (4xx) or `internal`
(5xx) as its code.

## Custom reasons

Each reason belongs to one universal code, so its status never varies.

| Reason | Code | Status | When |
| --- | --- | --- | --- |
| `origin_denied` | `forbidden` | 403 | A browser call from a site that is not the web app (STF_ALLOWED_ORIGINS). |
| `operator_required` | `forbidden` | 403 | An operator-only route without the operator's machine, token or signed-in cookie. |
| `operator_key_unknown` | `unauthenticated` | 401 | POST /operator/session with a key no operator has. |
| `operators_unconfigured` | `unavailable` | 503 | Operator sign-in on a server without STF_OPERATORS. |
| `too_many_requests` | `rate_limited` | 429 | A per-client rate limit (questions, voice, photos, commands, records). |
| `daily_budget_spent` | `rate_limited` | 429 | A daily cap shared by every instance (questions, spoken answers, photos). |
| `body_too_large` | `payload_too_large` | 413 | A request body over its route's limit. |
| `bad_content_length` | `bad_request` | 400 | A Content-Length header that is not a number. |
| `command_refused` | `bad_request` | 400 | The safety guard refused an order (bounds, e-stop, interlock); the message says why. |
| `incident_not_found` | `not_found` | 404 | Acknowledging a watchdog incident that does not exist. |
| `node_not_found` | `not_found` | 404 | An OPC UA node or method id the address space does not hold. |
| `node_write_refused` | `bad_request` | 400 | An OPC UA write the guard refused or a read-only node. |
| `submodel_not_found` | `not_found` | 404 | An AAS submodel id that does not exist. |
| `record_not_stored` | `internal` | 500 | The factory database did not take a twin record. |
| `actions_off` | `unavailable` | 503 | Guarded actions are not configured on this server; the message names the setting. |
| `proposal_not_found` | `not_found` | 404 | A proposal id that does not exist or is not the caller's. |
| `session_not_found` | `not_found` | 404 | A copilot session id that does not exist or is not the guest's. |
| `quality_not_found` | `not_found` | 404 | No quality record for that request id: an unknown id, one older than `STF_QUALITY_DAYS`, or a record not written yet. |
| `copilot_failed` | `internal` | 500 | The copilot failed in a way it did not expect (logged with its traceback). |
| `models_busy` | `unavailable` | 503 | Every Gemini model is cooling down after a rate limit. |
| `model_failed` | `upstream_failed` | 502 | A language model could not answer (a limit, a refused key, a timeout). |
| `cloud_token_missing` | `unavailable` | 503 | No Google Cloud token for the Vertex lane. |
| `nothing_to_say` | `bad_request` | 400 | A spoken answer requested for text with nothing speakable in it. |
| `voice_unavailable` | `unavailable` | 503 | No voice provider is configured or every one failed. |
| `transcriber_unavailable` | `unavailable` | 503 | No transcription provider is configured, or every model is at its limit. |
| `transcriber_failed` | `upstream_failed` | 502 | The transcription provider answered with an error. |
| `transcriber_timeout` | `upstream_timeout` | 504 | The transcription provider did not answer in time. |
| `audio_type_unsupported` | `unsupported_media_type` | 415 | A recording in a format the transcriber does not take. |
| `capture_off` | `unavailable` | 503 | Photo capture is switched off on this server. |
| `photo_not_found` | `not_found` | 404 | A photo id that does not exist or is not the guest's. |
| `photo_invalid` | `bad_request` | 400 | A photo that is not a JPEG of 32 to 1024 px, or an unknown flavour or source. |
| `photo_type_unsupported` | `unsupported_media_type` | 415 | A photo upload that is not image/jpeg. |
| `visits_unreachable` | `unavailable` | 503 | The visits store did not answer. |
| `notify_refused` | `conflict` | 409 | Owner notices are not configured, or a test from a local address is not armed. |
| `notify_failed` | `upstream_failed` | 502 | The owner notice could not be sent (SMTP or webhook). |

## Raising them

```python
from services.api.core.errors import AppError, Code, Reason

raise AppError(Reason.SESSION_NOT_FOUND, "no such session")   # a custom reason
raise AppError(Code.BAD_REQUEST, "a JSON object of at most 8 kB")  # a universal code alone
```

Exceptions raised inside the service and caught across modules derive from `ServiceError` and
carry the code a request fails with if one escapes: `ModelError` (`model_failed`), `AllBusy`
(`models_busy`), `NoToken` (`cloud_token_missing`), `Unavailable` (`voice_unavailable`).
Anything else that escapes is `internal`; its text is logged with the traceback and never sent.

To add a reason: add the member to `Reason` with its code, add a row here, and use it.
