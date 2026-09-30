# Code Review

The issues below are ordered by business impact. The review focuses on failures that can cause duplicate financial charges, payment loss, disclosure of restricted member data, or broken isolation between clubs.

## 1 Duplicate charge after an ambiguous session failure

- **File and line:** `app/services/session_flow.py:31-54`, especially the external charge at line 36
- **Category:** Data Integrity
- **Severity:** Critical

The payment provider is called before any durable idempotency record or completed-session state is stored. If the process fails after the provider accepts the charge but before line 54 commits the booking and session state, `awaiting_confirmation` remains true and the same confirmation can charge the member again; the condition at line 31 only checks that stale state and therefore does not catch the retry.

**Recommended fix:** Generate a stable idempotency key from the session/payment operation, persist a pending payment attempt before the external call, and pass that key to an idempotent provider API. Lock the session row while transitioning it, reconcile ambiguous provider outcomes by idempotency key, and return the already-recorded result for repeated `affirm` requests rather than issuing another charge.

### Request and response trace from the running instance

The session was created with this literal request:

```console
$ curl -sS -X POST http://127.0.0.1:8000/sessions -H "X-Member-Token: riverside-member-1"
{"session_id":1,"status":"active"}
```

The booking state was advanced with this literal request and response:

```console
$ curl -sS -X POST http://127.0.0.1:8000/sessions/1/turn -H "X-Member-Token: riverside-member-1" -H "Content-Type: application/json" -d '{"intent":"book","party_size":2}'
{"status":"awaiting_confirmation","party_size":2}
```

The first confirmation charged the provider and then simulated a process failure before database persistence:

```console
$ curl -sS -X POST http://127.0.0.1:8000/sessions/1/turn -H "X-Member-Token: riverside-member-1" -H "Content-Type: application/json" -d '{"intent":"affirm","amount_cents":5000,"simulate_crash":true}'
{"detail":"simulated crash after charge, before persistence"}
```

Retrying the same logical confirmation returned success:

```console
$ curl -sS -X POST http://127.0.0.1:8000/sessions/1/turn -H "X-Member-Token: riverside-member-1" -H "Content-Type: application/json" -d '{"intent":"affirm","amount_cents":5000}'
{"status":"confirmed","booking_id":3}
```

The provider-side charge log proves that the two requests produced two charges of 5,000 cents:

```console
$ curl -sS http://127.0.0.1:8000/sessions/debug/payment-charge-log -H "X-Member-Token: riverside-admin"
{"charges":[5000,5000]}
```

## 2 A member controls the amount charged for an existing booking

- **File and line:** `app/routers/bookings.py:28-40`, especially lines 29 and 35
- **Category:** Data Integrity
- **Severity:** Critical

The endpoint charges `payload.amount_cents`, a caller-controlled value, instead of the trusted `booking.amount_cents`, and marks the booking confirmed after any successful charge. A member can therefore submit a small positive amount for a much larger booking and have the full booking treated as paid, causing direct revenue loss and inconsistent payment records.

**Recommended fix:** Remove the amount from the public confirmation payload and always charge the amount stored on the authorized booking. Add server-side validation of the booking state and amount, reject confirmation of an already-paid booking, and protect the operation with a stable idempotency key.

**Resolution:** Fixed during post-assignment hardening. The endpoint now charges `booking.amount_cents`, persists `booking-confirmation:{booking.id}` before the provider call, validates any resumed attempt against the booking amount, and rejects an already-confirmed booking with HTTP 409.

## 3 Introduction endpoint exposes another club's restricted medical data

- **File and line:** `app/routers/introductions.py:19-25`
- **Category:** Data Isolation
- **Severity:** Critical

The authenticated member is never used to constrain either requested member ID to the caller's club, and both attribute queries omit the `club_id` and `restricted` predicates. Any authenticated member who can guess IDs can combine members across clubs and receive private health information verbatim in the generated introduction reason.

**Recommended fix:** Fetch both members using IDs plus `club_id == member.club_id`, return a non-enumerating 404 when either is outside the caller's club, and query only attributes from that same club with `restricted == False`. Apply the configured confidence threshold before generating text and return an insufficient-basis result when no safe evidence remains.

### Confirming trace

A Riverside member requested an introduction involving Oakhurst member 12. The response disclosed that member's restricted chronic-condition attribute:

```console
$ curl -sS "http://127.0.0.1:8000/introductions/3/12?reason=business" -H "X-Member-Token: riverside-member-1"
{"reason_text":"Because raising a seed round, looking for angel investors; might be raising again next year and recently diagnosed with a chronic condition — a good business match."}
```

## 4 Knowledge search leaks records across clubs

- **File and line:** `app/routers/knowledge.py:19-20,28-32`
- **Category:** Data Isolation
- **Severity:** High

The authorization check verifies that the path `club_id` equals the caller's club, but the subsequent nearest-neighbor query searches the global `knowledge_chunks` table without a club predicate. The check therefore authorizes the requested label rather than isolating the queried rows, allowing one club's policies and internal knowledge to appear in another club's response.

**Recommended fix:** Add `KnowledgeChunk.club_id == club_id` to the query before similarity ordering and retain the caller/path club check as defense in depth. Add a regression test that seeds a semantically closer cross-club chunk and proves it can never appear in the result set.

### Confirming trace

The request was explicitly made against Riverside, but three returned records belong to Oakhurst:

```console
$ curl -sS --get http://127.0.0.1:8000/clubs/riverside/knowledge/query --data-urlencode "q=collared shirts dining areas" -H "X-Member-Token: riverside-member-1"
[{"chunk_id":6,"club_id":"oakhurst","title":"Dress code","body":"Oakhurst requires collared shirts in all dining areas, no exceptions."},{"chunk_id":1,"club_id":"riverside","title":"Guest fees","body":"Riverside guest fees are $50 per visit, waived for members' immediate family."},{"chunk_id":8,"club_id":"oakhurst","title":"Cancellation policy","body":"Oakhurst bookings are non-refundable within 48 hours of the reservation."},{"chunk_id":4,"club_id":"riverside","title":"Cancellation policy","body":"Riverside bookings can be cancelled up to 24 hours ahead for a full refund."},{"chunk_id":5,"club_id":"oakhurst","title":"Guest fees","body":"Oakhurst guest fees are $75 per visit, capped at two guests per member per month."}]
```

## 5 Restricted attributes influence member matching

- **File and line:** `app/services/matching_service.py:9-12`
- **Category:** Security
- **Severity:** High

`build_member_profile_text` concatenates every attribute into the text used to create matching embeddings, including rows explicitly marked `restricted`. Although the raw text is not returned by the candidates endpoint, health, clinical, or psychometric information can still affect rankings and is sent into the matching representation, violating the stated privacy boundary.

**Recommended fix:** Centralize construction of matchable attributes in a query that requires the member's club and `MemberAttribute.restricted.is_(False)`, then use that safe query for every embedding refresh and on-demand profile build. Recompute existing profile embeddings from non-restricted data and add tests proving that adding or changing a restricted attribute cannot change the profile text or candidate score.
