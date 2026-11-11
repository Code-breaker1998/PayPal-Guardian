# PayPal Guardian Starter

**AI Agents Spend. Guardian Keeps You in Control.**

Phase 1 local prototype with a Next.js dashboard, FastAPI API, PostgreSQL, Docker Compose, a deterministic ALLOW / REVIEW / BLOCK engine, and an audit event.

## Run

```bash
cp .env.example .env
docker compose up --build
```

Open:

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

The API container creates the starter tables during startup. For production, replace this with Alembic migrations.

## Demo

Use the three dashboard buttons or run:

```bash
python demo-agent/send_intent.py
```

Expected decisions:

- Safe known merchant under $75: `ALLOW`
- New merchant and/or $75+: `REVIEW`
- Subscription, blocked category, or amount over $200: `BLOCK`

## Test decision rules

```bash
docker compose exec guardian-api pytest -q
```

## Next phase

1. Natural-language policy parser and policy versions
2. Ed25519 agent registration and signed intents
3. Approval endpoint and approval inbox
4. PayPal Sandbox OAuth, create order, approval and capture
5. Tamper-evident audit chain
