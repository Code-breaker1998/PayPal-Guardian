# PayPal Guardian

**PayPal Guardian** is a hackathon prototype for secure agentic commerce. It allows a self-hosted AI shopping agent to inspect products, recommend purchases, create cryptographically signed payment intents, and submit them to a Guardian control plane for merchant verification, policy enforcement, human review, and PayPal Sandbox checkout.

> **AI recommends. The agent signs. Guardian verifies. The customer stays in control.**

## What the project demonstrates

- Self-hosted AI recommendations using **Ollama** and **Qwen3**
- Browser extension product detection on live shopping pages
- Product extraction from JSON-LD, Open Graph, microdata, and DOM fallbacks
- Automatic merchant discovery for previously unseen domains
- Live HTTPS/TLS certificate and hostname validation
- Lookalike-domain and local blocklist checks
- Ed25519-signed payment intents
- Agent registration with `PENDING` to `ACTIVE` approval
- Purpose, timestamp, expiry, and replay protection
- Guardian decisions: `ALLOW`, `REVIEW`, and `BLOCK`
- Human approval for reviewed transactions
- PayPal Sandbox order creation and capture flow
- PostgreSQL audit trail and decision evidence

## Architecture

```text
Shopping website
      |
      v
Browser Extension
  - detects current product
  - extracts page evidence
      |
      v
Demo Agent :8100
  - normalizes product data
  - uses local Qwen through Ollama
  - creates Ed25519-signed intent
      |
      v
Guardian API :8000
  - verifies agent identity and signature
  - validates merchant domain and TLS
  - applies seller and spending policies
  - returns ALLOW / REVIEW / BLOCK
      |
      +--> Human Approval
      |
      +--> PayPal Sandbox
      |
      v
PostgreSQL :5432
  - agents
  - policies
  - payment intents
  - merchant trust evidence
  - discovered merchants
  - approvals
  - PayPal orders
  - audit events
```

## Services

| Service | Purpose | Local URL |
|---|---|---|
| Frontend | Dashboard, decisions, approvals | http://localhost:3000 |
| Guardian API | Security, merchant trust, policy, PayPal | http://localhost:8000 |
| Demo Agent | AI recommendation and signed intents | http://localhost:8100 |
| Ollama | Self-hosted Qwen inference | http://localhost:11434 |
| PostgreSQL | Persistent application data | localhost:5432 |

## Technology stack

- Python 3.12
- FastAPI
- SQLAlchemy 2
- PostgreSQL 16
- Next.js 15 and TypeScript
- Docker Compose
- Ollama with `qwen3:0.6b`
- Ed25519 via `cryptography`
- Microsoft Edge / Google Chrome Manifest V3 extension
- PayPal Sandbox Orders v2 API

## Repository structure

```text
paypal-guardian-starter/
├── browser-extension/
│   ├── manifest.json
│   ├── background.js
│   ├── content-script.js
│   ├── popup.html
│   ├── popup.css
│   └── popup.js
├── demo-agent/
│   ├── app.py
│   ├── agent.py
│   ├── catalog.py
│   ├── browser_page_router.py
│   ├── real_site_router.py
│   ├── real_website.py
│   ├── Dockerfile
│   └── requirements.txt
├── guardian-api/
│   ├── app/
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── security.py
│   │   ├── decision_engine.py
│   │   ├── merchant_trust/
│   │   ├── browser_discovery_models.py
│   │   ├── browser_discovery_router.py
│   │   ├── phase6_models.py
│   │   ├── phase6_schemas.py
│   │   ├── phase6_router.py
│   │   └── paypal_client.py
│   ├── tests/
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   └── styles.css
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml
├── .env.example
└── README.md
```

## Prerequisites

- Docker Desktop
- Git
- Microsoft Edge or Google Chrome for the browser extension
- A PayPal Developer Sandbox application for payment testing

## Environment configuration

Copy the example environment file:

```powershell
Copy-Item .env.example .env
```

Configure the following values in `.env`:

```env
PAYPAL_CLIENT_ID=your_sandbox_client_id
PAYPAL_CLIENT_SECRET=your_sandbox_client_secret
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
PAYPAL_RETURN_URL=http://localhost:3000/paypal/return
PAYPAL_CANCEL_URL=http://localhost:3000/paypal/cancel
OLLAMA_MODEL=qwen3:0.6b
```

Do not commit `.env`, private keys, PayPal secrets, or Docker volumes.

## Run locally

Start the services:

```powershell
docker compose up --build -d
```

Check status:

```powershell
docker compose ps
```

Expected services:

```text
postgres       healthy
ollama         healthy
guardian-api   healthy
demo-agent     healthy
frontend       running
```

### Install the local Qwen model

The model only needs to be pulled when the `ollama_data` volume is new or has been deleted:

```powershell
docker compose exec ollama ollama pull qwen3:0.6b
```

Verify:

```powershell
docker compose exec ollama ollama list
```

Avoid `docker compose down -v` during normal development because it removes PostgreSQL data, agent keys, and the Ollama model volume.

## Approve the demo agent

New agents are registered as `PENDING`. Activate the demo agent explicitly:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/api/v1/admin/agents/demo-shopping-agent/approve
```

## Install the browser extension locally in Developer Mode

The browser extension is currently distributed as an unpacked Manifest V3 extension for hackathon testing. It is not yet published to the Microsoft Edge Add-ons or Chrome Web Store.

### Extension files

Confirm that the repository contains:

```text
browser-extension/
├── manifest.json
├── background.js
├── content-script.js
├── popup.html
├── popup.css
└── popup.js
```

### Microsoft Edge installation

1. Start the local backend services:

   ```powershell
   docker compose up -d
   ```

2. Verify that the Demo Agent is healthy:

   ```powershell
   Invoke-RestMethod http://localhost:8100/health
   ```

3. Open Microsoft Edge and go to:

   ```text
   edge://extensions
   ```

4. Turn on **Developer mode**.
5. Select **Load unpacked**.
6. Select the complete `browser-extension` folder from the cloned repository. Do not select `manifest.json` individually.
7. Open the Edge **Extensions** menu, locate **PayPal Guardian Product Scanner**, and select **Show in toolbar**.
8. Open or refresh a shopping product page.
9. Select the PayPal Guardian extension icon in the browser toolbar.
10. Review the extracted product information and select **Analyze with Guardian**.

### Google Chrome installation

1. Open Google Chrome and go to:

   ```text
   chrome://extensions
   ```

2. Turn on **Developer mode**.
3. Select **Load unpacked**.
4. Select the complete `browser-extension` folder.
5. Pin **PayPal Guardian Product Scanner** from the Extensions menu.
6. Refresh the shopping product page before opening the extension popup.

### Expected extension behavior

The extension should display:

- Product name
- Price and currency
- Current hostname
- Extraction source
- Confidence level

After selecting **Analyze with Guardian**, the popup should display one of these decisions:

- `ALLOW`: merchant and product evidence passed the current trust policy
- `REVIEW`: customer approval or merchant verification is required
- `BLOCK`: the domain, TLS evidence, signature, or policy checks failed

### Important notes

- The extension currently calls the locally running Demo Agent at:

  ```text
  http://localhost:8100/agent/browser-extension-page/analyze
  ```

- Keep the `demo-agent` and `guardian-api` containers running while using the extension.
- After changing any file inside `browser-extension`, return to `edge://extensions` or `chrome://extensions`, select **Reload** for the extension, and refresh the product page.
- Browser-internal pages such as `edge://extensions`, `chrome://extensions`, browser settings, and extension-store pages cannot be scanned.
- The extension source code is available in the repository, but each tester must load it locally in Developer Mode until a store-published version is available.

### Troubleshooting

#### The extension does not appear

Confirm that Developer Mode is enabled and that the complete `browser-extension` folder was selected. The selected folder must contain `manifest.json` at its top level.

#### The popup says `Not Found`

Confirm that `browser-extension/background.js` calls exactly:

```text
http://localhost:8100/agent/browser-extension-page/analyze
```

Then reload the extension and refresh the product page.

#### The popup shows stale product information

Reload the extension, refresh the active product page, and clear the extension storage from the popup developer console if necessary:

```javascript
chrome.storage.local.clear()
```

#### The product is detected but analysis fails

Check the backend services:

```powershell
docker compose ps
docker compose logs demo-agent --tail 100
docker compose logs guardian-api --tail 100
```
## Test URLs

### Safe public scraping sandbox

```text
https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html
```

### Expected outcomes

- Registered merchant with valid TLS: `ALLOW`
- New merchant with valid TLS: `REVIEW`
- HTTP-only URL, invalid TLS, blocklisted domain, or lookalike domain: `BLOCK`

Do not intentionally browse to real malicious websites. Use controlled test pages or API/Swagger payloads for rejection tests.

## API documentation

- Guardian Swagger: http://localhost:8000/docs
- Demo Agent Swagger: http://localhost:8100/docs

Useful routes include:

```text
POST /api/v1/agents
POST /api/v1/admin/agents/{agent_id}/approve
POST /api/v1/payment-intents
GET  /api/v1/dashboard
GET  /api/v1/payment-intents/{intent_id}/audit
GET  /api/v1/approvals
POST /api/v1/payment-intents/{intent_id}/approve
POST /api/v1/payment-intents/{intent_id}/reject
POST /api/v1/payment-intents/{intent_id}/paypal-order
POST /api/v1/paypal/orders/{order_id}/capture
POST /api/v1/merchants/discover
GET  /api/v1/merchants/discovered
POST /agent/recommend
POST /agent/purchase
POST /agent/browser-extension-page/analyze
```

## Decision model

### ALLOW

Used when the agent signature is valid, the merchant and seller are verified, and the purchase is inside policy limits.

### REVIEW

Used for scenarios such as:

- Newly discovered merchant
- New marketplace seller
- Amount above the human-approval threshold
- Medium merchant trust

### BLOCK

Used for scenarios such as:

- Invalid agent signature
- Expired or replayed intent
- Merchant not registered when registration is mandatory
- Lookalike or blocklisted domain
- TLS validation failure
- Prohibited category or subscription
- Hard transaction limit exceeded

## Security controls

- Ed25519 signing and public-key verification
- Canonical JSON payloads
- Unique intent IDs and nonces
- Timestamp and expiry validation
- Guardian-owned merchant trust evaluation
- HTTPS and TLS certificate validation
- Exact-domain matching
- Lookalike and Punycode signals
- Private, loopback, and link-local destination rejection for website fetches
- Human approval for reviewed purchases
- PayPal credentials restricted to the Guardian API container
- Auditable security and payment events

## Tests

Run Guardian tests:

```powershell
docker compose exec guardian-api pytest -q
```

Compile Python modules:

```powershell
docker compose run --rm guardian-api python -m compileall -q app
docker compose run --rm demo-agent python -m compileall -q .
```

Build the frontend:

```powershell
docker compose run --rm frontend npm run build
```

## Troubleshooting

### Demo Agent is unhealthy

```powershell
docker compose logs demo-agent --tail 200
```

### Guardian API is unhealthy

```powershell
docker compose logs guardian-api --tail 200
```

### Model not found

```powershell
docker compose exec ollama ollama list
docker compose exec ollama ollama pull qwen3:0.6b
```

### Browser extension shows stale product data

Reload the extension, clear extension storage, and refresh the product page:

```javascript
chrome.storage.local.clear()
```

### Extension returns `Not Found`

Confirm the extension calls:

```text
http://localhost:8100/agent/browser-extension-page/analyze
```

## Prototype limitations

This is a hackathon prototype, not a production payment platform.

- PayPal runs in Sandbox mode
- Merchant discovery is automated, but new merchants require review
- Some commerce pages require site-specific extraction improvements
- Production deployment would require authenticated admin actions, mTLS or CA-issued agent identities, encrypted key storage, webhook verification, formal database migrations, monitoring, and compliance review

## Demo narrative

> A customer opens a product page. The browser extension extracts the product automatically. A self-hosted AI agent analyzes the product and creates a signed payment intent. Guardian independently verifies the agent, merchant, domain, TLS certificate, seller, and policy. Trusted purchases are allowed, uncertain purchases require human review, and suspicious purchases are blocked. Approved transactions continue through PayPal Sandbox.

## License

Add the license required by your hackathon rules. If no license is specified, consider the MIT License before making the repository public.
