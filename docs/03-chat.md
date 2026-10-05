# Step 3 — Chat with LibreChat and LiteLLM

This step connects [LibreChat](https://www.librechat.ai/) to the model provider
through [LiteLLM](https://www.litellm.ai/). In Step 4, we'll add tools for
querying the telemetry warehouse.

## 3.1 — Chat services and the workshop key

1. **LibreChat** — an open source chat UI with multi-user support, connections
   to multiple model providers, and [MCP](https://modelcontextprotocol.io/)
   support.
2. **LiteLLM** — an LLM gateway: one OpenAI-compatible HTTP API in front of
   100+ providers.
3. **The key on your card** — scoped to the workshop's model project and nothing
   else, and it expires at the end of the day. It reaches a handful of models;
   `task llm:check` prints exactly which.

## 3.2 — Gateway controls in LiteLLM

LibreChat can connect directly to an OpenAI-compatible provider, so LiteLLM
is optional. We include it to demonstrate:

1. **Budgets and usage tracking.** The gateway tracks requests routed through
   it and can apply per-key budgets and rate limits. Below, you'll create a
   key with a 50-cent budget and inspect its usage.
2. **Provider configuration.** Clients request a model alias; the gateway
   maps it to a provider and model. You can change that mapping without
   editing each client.
3. **Credential management.** LiteLLM holds the provider key, and clients use
   a gateway key. On a single-user laptop this offers limited isolation; it
   becomes more useful when multiple clients share a gateway.

These controls require an additional service to run and maintain. For a
personal setup, a direct provider connection may be sufficient.

## 3.3 — Configure and start the chat services

### 3.3.1 — Enter the workshop key

Copy `.env.example` to `.env` if you haven't, then put the key from your card
into it as `LLM_API_KEY`.

The key is about 170 characters, so rather than typing it, scan the QR code on
your card. Run `task up:docs` if it isn't already running, open
**[http://localhost:4321/creds/](http://localhost:4321/creds/)**, click *Start
camera*, hold the card up, and copy the two lines it decodes into `.env`.

The scanner runs locally. It decodes the QR code in your browser using a
JavaScript library bundled with the site at build time. It does not send the
credential over the network or fetch a decoder from a CDN. You can also enter
the two lines from the card manually.

### 3.3.2 — Check access to the workshop models

Check the key to list available models and catch configuration errors before
starting the chat services:

```bash
task llm:check
```

### 3.3.3 — Start the chat services

```bash
# postgres, litellm, mongodb, librechat
task up:chat
```

### 3.3.4 — Create a local LibreChat account

Open [LibreChat](http://localhost:3080) and register an account. This is your
local instance; email verification is off.

## 3.4 — Create a budget-limited gateway key

Open [LiteLLM's dashboard](http://localhost:4000/ui) and log in as `admin`
with your `LITELLM_MASTER_KEY`. Use the dashboard to inspect virtual keys,
budgets, and usage.

Run this command to create a key with a 50-cent budget:

```bash
# a key of your own, capped at 50 cents
curl -s http://localhost:4000/key/generate \
  -H "Authorization: Bearer sk-workshop" -H "Content-Type: application/json" \
  -d '{"models":["workshop-default"],"max_budget":0.50,"key_alias":"mine"}'
```

Use the `sk-...` it returns instead of `sk-workshop` to track calls against
that budget in the dashboard.

## 3.5 — Test the model API

Test LiteLLM's OpenAI-compatible API on port 4000:

```bash
curl -s http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-workshop" -H "Content-Type: application/json" \
  -d '{"model": "workshop-default", "messages": [{"role": "user", "content": "ping"}]}'
```

## 3.6 — Send a message in LibreChat

LibreChat sends requests to the same endpoint. Open a new chat, pick
**Workshop Models → workshop-default**, and send a message.

`workshop-default` is an alias, not a model. The picker lists every model your
key can reach — the gateway asks the provider at startup rather than keeping a
list in this repo. The alias points at a model selected for tool calling in
Steps 4 and 5. You can try the other models for chat; use the default for the
tool exercises.

## 3.7 — Configure another provider (optional)

To configure another provider behind the same endpoint, add an entry to
`litellm/config.yaml`:

```yaml
  - model_name: my-model
    litellm_params:
      model: anthropic/claude-sonnet-5     # or vertex_ai/..., azure/..., ollama/...
      api_key: os.environ/MY_PROVIDER_KEY
```

Set `MY_PROVIDER_KEY` to your provider key. LibreChat and your scripts can use
the new model name through the same `http://localhost:4000/v1` endpoint.

## 3.8 — Check the model's warehouse access

Ask it: *"How many telemetry samples are in the readings table?"*

The model has no connection to the warehouse yet, so it cannot verify the
answer. It may decline to answer or invent a number. In the next step, we'll
use MCP to expose query tools and return their results to the conversation.

Next: [Step 4 — Build an MCP server for Trino](04-mcp-server.md)
