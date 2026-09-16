# WoolGate · AI Aggregation Gateway

> **中文**：[README.zh-CN.md](README.zh-CN.md) · **English**: below

**WoolGate is a self-hosted, open-source AI aggregation gateway: it unifies free LLM APIs from Chinese vendors behind one OpenAI-compatible endpoint, with smart cost-saving routing, 30-second Docker deployment, and local-model fallback. Apache-2.0.**

Clients (Dify / OpenClaw / any OpenAI-compatible tool) configure a single address and a single model name. WoolGate handles the rest: free-tier quota scheduling, task-based routing, local-model offload, and context management. One-time setup, everything else is automatic.

## Why WoolGate

Everyday LLM usage wastes money in three ways:

1. **Using paid models for tasks free models can handle** — casual chat, translation, and simple Q&A work fine on free models, but most clients only support one paid model and burn money indiscriminately.
2. **Using expensive models for cheap tasks** — coding, image, and video models cost tens of times more; the most expensive model gets used for the most trivial work.
3. **Using cloud models for work a local model can do** — high-frequency low-difficulty calls like classification, embedding, and simple Q&A can be handled by a small local model at near-zero cost.

WoolGate's smart routing is designed for exactly these three types of waste: **free-tier first, task-based classification, cost-ordered selection, local-model offload** — every request is sent to the most economical model.

## Core Features

- **Free Tier Wizard** — built-in catalog of mainstream free model vendors (DeepSeek, Tongyi/Qwen, Kimi, Zhipu/GLM, Doubao, Hunyuan, Qianfan, etc.). Paste the API Key you got from registration; one click auto-completes "create account → sync models → compute capability vectors → enable", all in ~30 seconds.
- **Smart Routing** — requests are classified by task (coding / creative writing / chat / embedding / general), then routed tier by tier through "free-first → cost-first → fallback" to the most economical available model. Routing decisions can use LLM-driven or vector-based matching, both preferring local/free models.
- **Unified Model Name** — clients configure one external model name (default `woolgate`), and the gateway routes internally. You can also specify a real model name to pin a specific model directly.
- **Account Management** — vendor → account (API Key) → model three-tier structure: one Key mounts all models of that vendor, with enable/disable, smart sync, and encrypted Key storage.
- **Model Catalog** — built-in model directory (local models + free models + vendor models), with filtering and one-click onboarding.
- **Context Management** — three strategies: window truncation / summary compression / passthrough, so long conversations never blow the context.
- **Local Model Support** — built-in Ollama support; local models handle embedding, task classification, and simple Q&A, keeping data on-premises.
- **Streaming Safety** — account is locked once SSE streaming starts, preventing context fragmentation from mid-stream model switching.
- **Quota Prediction & Smart Retry** — predicts remaining quota before a request to avoid mid-stream exhaustion; exponential backoff + jitter retry prevents thundering herds.
- **Web Admin Panel** — Free Tier Wizard, Account Management, Model Catalog, Pipeline Policy, System Config, and Logs in one visual console.
- **One-Command Docker Deployment** — out of the box, image trimmed to ~400MB.

## Quick Start

### 1. Start the service

```bash
git clone https://github.com/SuperWang-AI/woolgate.git
cd woolgate
cp .env.example .env   # generate and fill ENCRYPTION_KEY and GATEWAY_BEARER_TOKEN per the comments
docker compose up -d
```

### 2. Open the admin panel

Visit **http://localhost:8765/admin**

### 3. One-click onboarding via the Free Tier Wizard

From the admin home, open the Free Tier Wizard, pick a vendor you've registered (e.g. DeepSeek), paste your API Key, and click one-click configure — account, models, and capability vectors are all created automatically. No manual maintenance.

### 4. Connect your client

In Dify / OpenClaw / any OpenAI-compatible tool:

- **Base URL**: `http://<woolgate-address>:8765/v1`
- **API Key**: your `GATEWAY_BEARER_TOKEN`
- **Model name**: `woolgate` (smart routing) or a real model name (e.g. `deepseek-chat`, pinned)

See [QUICKSTART.md](QUICKSTART.md) for details.

## Client Setup Examples

### Dify

"Settings → Model Providers → OpenAI-API-compatible" and add:

| Setting | Value |
|---|---|
| Model Name | `woolgate` |
| Base URL | `http://woolgate:8765/v1` (when on the same Docker network) |
| API Key | your `GATEWAY_BEARER_TOKEN` |

### OpenClaw

```yaml
model:
  provider: openai-compatible
  base_url: http://woolgate:8765/v1
  api_key: your-gateway-bearer-token
  model: woolgate
```

### curl direct test

```bash
curl -X POST http://localhost:8765/v1/chat/completions \
  -H "Authorization: Bearer ${GATEWAY_BEARER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"model": "woolgate", "messages": [{"role": "user", "content": "Hello"}], "stream": true}'
```

## How Smart Routing Saves Money (Demo)

Open **`static/wg_routing_demo.html`** in the repo (any browser) to watch an animated walkthrough of one request flowing from client → gateway → smart classification → routing decision → model pool: how chat is routed to the most economical model, how local models offload cheap work, and how the best-matching free model is picked within a domain.

## Architecture Overview

```
Clients (Dify / OpenClaw / OpenAI-compatible)
        │  OpenAI-compatible protocol /v1
        ▼
┌─────────────────── WoolGate Gateway ──────────────────┐
│  API Layer      /v1/chat/completions  /v1/models      │
│  Pipeline       classify → route → select → execute   │
│  Routing        LLM / vector / free-first / cost-first│
│  Selectors      free-first · cost-first · sticky · RR │
│  Context        window / summary compression / direct │
│  Extension      9 lifecycle hooks · plugin SDK · SPI  │
│  Accounts       vendor → account(Key) → model, enc.   │
│  Admin          /admin (wizard / accounts / catalog)  │
└───────────────────────────────────────────────────────┘
        │
        ▼
  Model Pool (DeepSeek / Qwen / Kimi / GLM / Doubao / Ollama …)
```

> Since v0.6.0, WoolGate supports componentization/pluginization: the classification engine, client adapters, session storage, security review, and more can be replaced via SPI; plugins are loaded via the `WOOLGATE_PLUGINS` env var and skipped on failure without blocking startup. See [ARCHITECTURE.md](ARCHITECTURE.md#七组件化插件化v060) and [docs/extensions/](docs/extensions/).

## Project Structure

```
woolgate/
├── app/
│   ├── models/          # Data models (vendor / account / model / log)
│   ├── pipeline/        # Request pipeline (routing / selectors / context / executor)
│   ├── extensions/      # Extension layer (hooks / SDK / SPI / plugin loader)
│   ├── routes/          # OpenAI-compatible API
│   ├── services/        # Business services (wizard / catalog / accounts / quota / session / health)
│   ├── ui/              # Admin panel
│   └── config.py        # Configuration management
├── docs/extensions/     # Extension contract docs (01~06)
├── examples/plugins/    # Example plugin templates
├── static/              # Static assets (routing demo page, etc.)
├── tests/               # Unit tests (pytest, CI regression)
├── main.py              # Main application entry
├── requirements.txt     # Python dependencies
├── Dockerfile           # Docker image
├── docker-compose.yml   # Docker orchestration
└── .env.example         # Environment variable example
```

## Admin Panel

| Page | Description |
|---|---|
| Home | Overview + guided onboarding (AI gateway setup wizard) |
| Free Tier Wizard | One-click free model onboarding |
| Account Management | Vendor / account / model three-tier management |
| Model Catalog | Built-in model directory & filtering |
| Pipeline Policy | Routing & context policy configuration |
| System Config | Global configuration |
| Logs | Request logs & statistics |

## Enterprise Edition

The open-source edition targets individuals and self-use: it aggregates free quotas from various vendors and schedules them intelligently. **Teams and organizations** can upgrade to the Enterprise Edition for:

- **Multi-tenancy** — team/project isolation with independent keys and permissions
- **Quota budgets** — per-tenant usage stats with auto-disable on over-limit
- **Audit & billing** — per-tenant isolated logs and cost details
- **Local smart saving mode** — local embedding + local classification + local simple Q&A, data never leaves your network

The Enterprise Edition entrance is reserved in the open-source version and is planned for release soon. For early access, contact the author via the project home page.

## Security Notes

- API Keys are encrypted with Fernet (`ENCRYPTION_KEY`)
- Gateway auth relies on `GATEWAY_BEARER_TOKEN` — use a strong random value
- Recommended for intranet use only; do not expose directly to the public internet
- Only manually-imported self-owned accounts are supported; no auto-registration, SMS-receiving, or similar capabilities

## Tech Stack

- **Backend**: FastAPI + Uvicorn
- **Database**: SQLite + SQLAlchemy (async)
- **Protocol adapter**: LiteLLM SDK
- **Encryption**: Cryptography (Fernet)
- **Scheduling**: APScheduler
- **Admin panel**: Custom web UI
- **Deployment**: Docker + Docker Compose

## Development

```bash
pip install -r requirements.txt
python main.py          # local startup
pytest tests/           # run unit tests
```

## FAQ

**Q: What model name should the client use?**
A: Use `woolgate` for smart routing; to pin a specific model, use the vendor's real model name (e.g. `deepseek-chat`) for direct connection.

**Q: I can't find a vendor I want in the Free Tier Wizard?**
A: The built-in catalog covers mainstream free-model vendors in China; you can also add models manually in the Model Catalog, or add accounts manually in Account Management.

**Q: How do I connect an Ollama local model?**
A: Make sure Ollama is running; in Docker deployments, access the host via `host.docker.internal:11434` from inside the container.

**Q: What if streaming is interrupted?**
A: Check whether the account quota is sufficient, and inspect the error details in the admin logs.

## License

[Apache License 2.0](LICENSE) © 2026 SuperWang-AI
