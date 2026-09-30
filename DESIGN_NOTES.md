# Design Notes

## Part 2 Multi Turn Session Flow

`advance_turn` in `app/services/session_flow.py` now persists a pending `Booking` and `PaymentAttempt` before calling the provider and derives the stable key `session-confirmation:{session.id}` for every retry of the same confirmation. `PaymentMockClient.charge` applies that key at the provider boundary, while the locked session lookup in `app/routers/sessions.py` and the stored attempt let a retry resume the original operation instead of creating another booking or charge. A repeated confirmation returns the existing `booking_id`, including when the retry supplies a different amount, because the persisted amount and operation identity remain authoritative.

## Part 3 Structured Extraction Pipeline

### Prompt and output design

The extraction prompt was designed after reviewing every seeded `ConversationMessage` and all four records in `eval/golden_set.json`. The production `OpenAIExtractionClient` uses the OpenAI Responses API with a strict JSON schema, permits zero or more attributes, preserves key terms from the source message, and explicitly treats health, clinical, and psychometric content such as diagnoses, anxiety, and therapy as restricted.

### Idempotency

The idempotency key is `source_message_id`, and the exact check in `app/services/extraction_service.py` is `MemberAttribute.source_message_id == message.id`. The service locks the source `ConversationMessage`, skips the LLM call when at least one row already carries that key, and commits all attributes for one message together, so a repeated request cannot create duplicate attribute rows; a valid zero-attribute result may be evaluated again because the supplied schema has no separate processed marker, but it still creates zero duplicate rows.

### Restricted data enforcement

Restricted attributes are deliberately retained in `member_attributes` with `restricted=True` for audit and privacy-aware use. Before any text reaches an embedding or live ranking query, `build_member_profile_text` in `app/services/matching_service.py` applies the actual predicate `MemberAttribute.restricted.is_(False)` together with the member and club predicates; extraction refreshes the member embedding through that same safe builder in the same transaction, so restricted text never enters the matching representation.

### Retry strategy and batch isolation

The retry strategy in `extract_with_retry` retries only `TransientLLMError` failures caused by timeouts, network failures, HTTP 429, or HTTP 5xx responses, using three attempts with exponential backoff and jitter. `extract_message_batch` wraps each message independently and rolls back only that message's transaction, so if message 3 in a batch of 5 fails permanently, result 3 is marked `failed`, processing continues to message 4, and message 4 can commit successfully.

### Evaluation threshold

The real-API evaluation assigns one point each for kind, restricted equality, and expected-keyword presence, for 12 possible points across the four golden records. The pass threshold is 0.80, requiring at least 10 of 12 checks and allowing at most two isolated model mistakes while still requiring broadly correct semantic and privacy behavior; the script prints every component and exits non-zero below that threshold.

## Part 4a Grounded Introduction Reasons

The introduction endpoint filters by the caller's club, `MemberAttribute.restricted.is_(False)`, and `MemberAttribute.confidence >= threshold` before constructing any output text, so excluded values never enter the renderer. The threshold defaults to the `INTRODUCTION_CONFIDENCE_THRESHOLD` environment setting and can be overridden by the validated `confidence_threshold` request parameter; the response returns the exact source attribute IDs and values for audit, or `insufficient basis for an introduction` when no rows qualify.

## Part 4b Grounded Knowledge Answers

The `knowledge_question` branch in `advance_turn` calls `find_grounded_knowledge` with `session.club_id`, and that service searches only the club's chunks and requires at least one meaningful lexical term in common with the question. A match returns the stored chunk body verbatim plus its chunk ID, title, matched terms, and score; no match sets the session state to `escalated` and returns `{"status": "escalate"}` instead of asking a model to guess.

## Closing Question

Given the fixed time, I deliberately did not replace the synchronous extraction endpoint with a durable background queue or add database uniqueness constraints, because the assignment prohibits schema changes and prioritizes a working audited pipeline. With one more day, I would propose a migration for a unique extraction key and explicit processed-zero marker, add provider reconciliation and observability for extraction retries, and load-test concurrent extraction and payment-confirmation requests before production deployment.

## Additional Payment Integrity Hardening

After completing the required and bonus parts, I fixed the separate direct-booking underpayment issue identified in `REVIEW.md`. `confirm_payment` now ignores request-body amounts, charges the authoritative `booking.amount_cents`, persists the stable key `booking-confirmation:{booking.id}` before the provider call, verifies a resumed attempt has the same amount, and returns HTTP 409 without another provider call when the booking is already confirmed.
