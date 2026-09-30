# Terminal Log

## Part 2 Before Fix

The original flow charged 5,000 cents, crashed before persistence, and charged the same amount again on retry.

```console
$ curl -sS -X POST http://127.0.0.1:8000/sessions -H "X-Member-Token: riverside-member-1"
{"session_id":1,"status":"active"}

$ curl -sS -X POST http://127.0.0.1:8000/sessions/1/turn -H "X-Member-Token: riverside-member-1" -H "Content-Type: application/json" -d '{"intent":"book","party_size":2}'
{"status":"awaiting_confirmation","party_size":2}

$ curl -sS -X POST http://127.0.0.1:8000/sessions/1/turn -H "X-Member-Token: riverside-member-1" -H "Content-Type: application/json" -d '{"intent":"affirm","amount_cents":5000,"simulate_crash":true}'
{"detail":"simulated crash after charge, before persistence"}

$ curl -sS -X POST http://127.0.0.1:8000/sessions/1/turn -H "X-Member-Token: riverside-member-1" -H "Content-Type: application/json" -d '{"intent":"affirm","amount_cents":5000}'
{"status":"confirmed","booking_id":3}

$ curl -sS http://127.0.0.1:8000/sessions/debug/payment-charge-log -H "X-Member-Token: riverside-admin"
{"charges":[5000,5000]}
```

## Part 2 After Fix

The retry deliberately changed the submitted amount to 7,000 cents, followed by another confirmation at 9,000 cents. Both requests resumed or returned the original operation and the provider ledger retained only the original 5,000-cent charge.

```console
$ curl -sS -X POST http://127.0.0.1:8000/sessions -H "X-Member-Token: riverside-member-1"
{"session_id":2,"status":"active"}

$ curl -sS -X POST http://127.0.0.1:8000/sessions/2/turn -H "X-Member-Token: riverside-member-1" -H "Content-Type: application/json" -d '{"intent":"book","party_size":2}'
{"status":"awaiting_confirmation","party_size":2}

$ curl -sS -X POST http://127.0.0.1:8000/sessions/2/turn -H "X-Member-Token: riverside-member-1" -H "Content-Type: application/json" -d '{"intent":"affirm","amount_cents":5000,"simulate_crash":true}'
{"detail":"simulated crash after charge, before persistence"}

$ curl -sS -X POST http://127.0.0.1:8000/sessions/2/turn -H "X-Member-Token: riverside-member-1" -H "Content-Type: application/json" -d '{"intent":"affirm","amount_cents":7000}'
{"status":"confirmed","booking_id":4}

$ curl -sS -X POST http://127.0.0.1:8000/sessions/2/turn -H "X-Member-Token: riverside-member-1" -H "Content-Type: application/json" -d '{"intent":"affirm","amount_cents":9000}'
{"status":"confirmed","booking_id":4}

$ curl -sS http://127.0.0.1:8000/sessions/debug/payment-charge-log -H "X-Member-Token: riverside-admin"
{"charges":[5000]}
```

## Part 2 Test Run

```console
$ DATABASE_URL='postgresql+psycopg://kindred:kindred@localhost:5434/kindred_test' .venv/bin/python -m pytest -q
........                                                                 [100%]
8 passed, 51 warnings in 0.27s
```

## Part 3 Test Run

```console
$ DATABASE_URL='postgresql+psycopg://kindred:kindred@localhost:5434/kindred_test' .venv/bin/python -m pytest -q
............                                                             [100%]
12 passed, 59 warnings in 0.42s
```

## Part 3 First Real Evaluation Attempt

The evaluator made a real authenticated OpenAI Responses API call and exhausted its three-attempt retry strategy. The provider returned HTTP 429 because the supplied project had no remaining API credits, so the evaluator exited non-zero as designed.

```console
$ .venv/bin/python -m scripts.eval_extraction
Traceback (most recent call last):
  ...
app.llm_client.TransientLLMError: OpenAI transient HTTP status 429

$ # Credential-only diagnostic; the API key itself was not printed
status= 200
authentication=ok

$ # Responses API error metadata; the API key itself was not printed
status= 429
type= insufficient_quota
code= credit_balance_exhausted
message= You have no credits remaining. Add credits to continue using the API at https://platform.openai.com/settings/organization/billing/.
```

## Part 3 Successful Real Evaluation

```console
$ .venv/bin/python -m scripts.eval_extraction
record=1 kind=True restricted=True keyword=True score=3/3 attributes=[{"kind": "need", "text": "intros to VCs", "confidence": 0.9, "restricted": false}]
record=2 kind=True restricted=True keyword=True score=3/3 attributes=[{"kind": "offer", "text": "led fundraising for three Series A rounds", "confidence": 0.9, "restricted": false}]
record=3 kind=True restricted=True keyword=True score=3/3 attributes=[{"kind": "context", "text": "been in therapy for the last year and it's helped a lot", "confidence": 0.9, "restricted": true}]
record=4 kind=True restricted=True keyword=True score=3/3 attributes=[{"kind": "interest", "text": "weekly running club on Tuesday mornings", "confidence": 0.9, "restricted": false}]
overall=12/12 score=1.000 threshold=0.800
```

## Part 3 Real API Batch Demonstration

Five additional messages were inserted into the running database for this demonstration without changing `scripts/seed.py` or its seed data.

```console
$ curl -sS -X POST http://127.0.0.1:8000/clubs/riverside/extract-attributes -H "X-Member-Token: riverside-admin" -H "Content-Type: application/json" -d '{"message_ids":[10,11,12,13,14]}'
{"club_id":"riverside","results":[{"message_id":10,"status":"processed","attribute_count":1},{"message_id":11,"status":"processed","attribute_count":1},{"message_id":12,"status":"processed","attribute_count":1},{"message_id":13,"status":"processed","attribute_count":2},{"message_id":14,"status":"processed","attribute_count":1}],"processed":5,"failed":0}
```

The identical second request performed no new LLM extraction and created no duplicate rows:

```console
$ curl -sS -X POST http://127.0.0.1:8000/clubs/riverside/extract-attributes -H "X-Member-Token: riverside-admin" -H "Content-Type: application/json" -d '{"message_ids":[10,11,12,13,14]}'
{"club_id":"riverside","results":[{"message_id":10,"status":"already_processed","attribute_count":1},{"message_id":11,"status":"already_processed","attribute_count":1},{"message_id":12,"status":"already_processed","attribute_count":1},{"message_id":13,"status":"already_processed","attribute_count":2},{"message_id":14,"status":"already_processed","attribute_count":1}],"processed":0,"failed":0}
```

The stored extraction rows include the restricted health attribute:

```console
$ docker compose exec -T db psql -U kindred -d kindred -Atc "select source_message_id,kind,text,confidence,restricted from member_attributes where source_message_id between 10 and 14 order by source_message_id,id;"
10|need|introductions to climate-tech seed investors|0.9|f
11|offer|happy to mentor others|0.9|f
12|context|therapy for anxiety|1|t
13|need|regular tennis partner|0.9|f
13|interest|Sunday mornings|0.8|f
14|offer|run a product design studio focused on mobile applications|0.9|f
```

The member associated with message 12 has no unrestricted attributes, so the restricted-safe matching profile is an empty string:

```console
$ .venv/bin/python - <<'PY'
from app.db import SessionLocal
from app.models import Member
from app.services.matching_service import build_member_profile_text
with SessionLocal() as db:
    member = db.get(Member, 5)
    print(build_member_profile_text(member, db))
PY

```

## Part 3 Final Test Run

```console
$ DATABASE_URL='postgresql+psycopg://kindred:kindred@localhost:5434/kindred_test' .venv/bin/python -m pytest -q
.............                                                            [100%]
13 passed, 59 warnings in 0.70s
```

## Part 4a Grounded Introduction Demonstration

The request-level threshold excludes the seeded 0.3-confidence attribute, while the response exposes every included source for audit:

```console
$ curl -sS --get http://127.0.0.1:8000/introductions/3/4 --data-urlencode "reason=business" --data-urlencode "confidence_threshold=0.8" -H "X-Member-Token: riverside-member-1"
{"reason_text":"Grounded business introduction — Riverside Member 1: raising a seed round, looking for angel investors; introductions to climate-tech seed investors | Riverside Member 2: angel investor, has backed a dozen seed-stage startups; happy to mentor others","source_attributes":[{"attribute_id":1,"member_id":3,"kind":"need","text":"raising a seed round, looking for angel investors","confidence":0.9},{"attribute_id":10,"member_id":3,"kind":"need","text":"introductions to climate-tech seed investors","confidence":0.9},{"attribute_id":3,"member_id":4,"kind":"offer","text":"angel investor, has backed a dozen seed-stage startups","confidence":0.95},{"attribute_id":11,"member_id":4,"kind":"offer","text":"happy to mentor others","confidence":0.9}],"confidence_threshold":0.8}
```

Member 5 has only restricted context and member 8 has no qualifying attributes, so the endpoint refuses to invent a reason:

```console
$ curl -sS --get http://127.0.0.1:8000/introductions/5/8 --data-urlencode "reason=business" -H "X-Member-Token: riverside-member-1"
{"reason_text":"insufficient basis for an introduction","source_attributes":[],"confidence_threshold":0.75}
```

## Part 4a Test Run

```console
$ DATABASE_URL='postgresql+psycopg://kindred:kindred@localhost:5434/kindred_test' .venv/bin/python -m pytest -q
................                                                         [100%]
16 passed, 60 warnings in 1.42s
```

## Part 4b Grounded Knowledge Demonstration

A matching Riverside knowledge source returns its stored body verbatim with retrieval evidence:

```console
$ curl -sS -X POST http://127.0.0.1:8000/sessions -H "X-Member-Token: riverside-member-1"
{"session_id":3,"status":"active"}

$ curl -sS -X POST http://127.0.0.1:8000/sessions/3/turn -H "X-Member-Token: riverside-member-1" -H "Content-Type: application/json" -d '{"intent":"knowledge_question","question":"What is the dress code?"}'
{"status":"answered","answer":"Riverside's dress code is smart casual after 6pm, resort wear during the day.","source":{"chunk_id":2,"title":"Dress code","matched_terms":["code","dress"],"score":1.0}}
```

An unrelated question has no grounded source and escalates instead of generating an answer:

```console
$ curl -sS -X POST http://127.0.0.1:8000/sessions -H "X-Member-Token: riverside-member-1"
{"session_id":4,"status":"active"}

$ curl -sS -X POST http://127.0.0.1:8000/sessions/4/turn -H "X-Member-Token: riverside-member-1" -H "Content-Type: application/json" -d '{"intent":"knowledge_question","question":"Can I bring my dog?"}'
{"status":"escalate"}
```

## Part 4b Final Test Run

```console
$ DATABASE_URL='postgresql+psycopg://kindred:kindred@localhost:5434/kindred_test' .venv/bin/python -m pytest -q
..................                                                       [100%]
18 passed, 60 warnings in 0.98s
```
