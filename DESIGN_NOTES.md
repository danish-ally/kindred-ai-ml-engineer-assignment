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
