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
