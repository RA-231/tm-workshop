# Step 3 — Getting Ready for MCP: LibreChat + LiteLLM

Welcome back from the break. The plan for the second half: put a language
model in front of our telemetry warehouse. This step wires up the chat
infrastructure; Step 4 gives the model tools.

## The pieces

- **LibreChat** — an open source ChatGPT-style UI. Multi-user, works with any
  model provider, and — the reason we chose it — first-class MCP support.
- **LiteLLM** — an LLM gateway: one OpenAI-compatible HTTP API in front of
  100+ providers, including AWS Bedrock.
- **AWS Bedrock** — where the actual Claude models run, using the Bedrock API
  key on your workshop card. That key is a bearer token: it can only call
  Bedrock, it expires at the end of the day, and it is not an AWS access key —
  it gives no console, no S3, no IAM.

## Do we really need LiteLLM?

Honest answer: **for this workshop, no.** LibreChat supports Bedrock natively
(`BEDROCK_AWS_ACCESS_KEY_ID` etc. in the env) — we could delete a whole
service.

We keep it anyway, deliberately:

1. **One place for the credential.** Your Bedrock key lives in LiteLLM's
   environment and nowhere else. Every other client — LibreChat today, your
   scripts tomorrow — gets a scoped master key instead of the cloud
   credential.
2. **A control point.** Per-key rate limits and spend tracking have to live
   somewhere, and a gateway is where. That is what the LiteLLM dashboard at
   [http://localhost:4000/ui](http://localhost:4000/ui) is for.
3. **Swappability.** Point `claude-sonnet` at a different provider and no
   client changes. This is how real platforms decouple "what apps ask for"
   from "what infrastructure serves it."

That's the trade-off to remember: a gateway is one more container in exchange
for credential isolation and control. If you rebuild this at home for
yourself alone, skip it.

## Bring it up

Put the Bedrock API key from your card into `.env` (copy `.env.example` if you
haven't) as `AWS_BEARER_TOKEN_BEDROCK`.

The key is 132 characters, so rather than typing it, scan the QR code on your
card. Run `task up:docs` if it isn't already running, open
**[http://localhost:4321/creds](http://localhost:4321/creds)**, click *Start
camera*, hold the card up, and copy the three lines it decodes into `.env`.

That page is worth a second's thought, because it is doing something you should
normally refuse to do — putting a live credential through a web page. It is
safe here for reasons that are all structural, not promises: it is served from
*your* laptop, the QR is decoded in your browser by a JavaScript library
vendored into this repo rather than fetched from a CDN, and the page makes no
network requests at all. Pull your network cable out and it still works. If
someone hands you a scanner page that doesn't meet that bar, type the key
instead.

```bash
task up:chat     # postgres, litellm, mongodb, librechat
```

- LibreChat: [http://localhost:3080](http://localhost:3080) — register any
  account (it's your local instance; email verification is off).
- LiteLLM's dashboard: [http://localhost:4000/ui](http://localhost:4000/ui) —
  log in as `admin` with your `LITELLM_MASTER_KEY`. This is the gateway's
  control point from earlier, made concrete: mint a virtual key with a budget,
  spend against it, watch the spend climb.

```bash
# a key of your own, capped at 50 cents
curl -s http://localhost:4000/key/generate \
  -H "Authorization: Bearer sk-workshop" -H "Content-Type: application/json" \
  -d '{"models":["claude-sonnet-5"],"max_budget":0.50,"key_alias":"mine"}'
```

  Use the `sk-...` it returns instead of `sk-workshop` and the dashboard will
  track every call against that budget. That is the whole argument for running a
  gateway, in one exercise.
- LiteLLM speaks OpenAI's API on port 4000. Prove it from the terminal:

```bash
curl -s http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-workshop" -H "Content-Type: application/json" \
  -d '{"model": "claude-sonnet", "messages": [{"role": "user", "content": "ping"}]}'
```

That same call, made by LibreChat on your behalf, is everything the chat UI
is. Open a new chat, pick **Workshop Models → claude-sonnet**, and say hello.

## What the model can't do yet

Ask it: *"How many telemetry samples are in the readings table?"*

It will make something up, or admit it has no idea — it has no connection to
our warehouse whatsoever. The model only knows what's in its prompt. Giving
it a way to *find out* — tools it can call, with the results fed back into
the conversation — is exactly what MCP standardizes.

Next: [Step 4 — Build an MCP server for Trino](04-mcp-server.md)
