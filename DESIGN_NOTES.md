# Design Notes

## Part 2 Multi Turn Session Flow

`advance_turn` in `app/services/session_flow.py` now persists a pending `Booking` and `PaymentAttempt` before calling the provider and derives the stable key `session-confirmation:{session.id}` for every retry of the same confirmation. `PaymentMockClient.charge` applies that key at the provider boundary, while the locked session lookup in `app/routers/sessions.py` and the stored attempt let a retry resume the original operation instead of creating another booking or charge. A repeated confirmation returns the existing `booking_id`, including when the retry supplies a different amount, because the persisted amount and operation identity remain authoritative.
