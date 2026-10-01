# Step 3 — Getting Ready for MCP: LibreChat + LiteLLM

Welcome back from the break. The plan for the second half: put a language
model in front of our telemetry warehouse. This step wires up the chat
infrastructure; Step 4 gives the model tools.

## The pieces

- **LibreChat** — an open source ChatGPT-style UI. Multi-user, works with any
  model provider, and — the reason we chose it — first-class MCP support.
- **LiteLLM** — an LLM gateway: one OpenAI-compatible HTTP API in front of
  100+ providers.
- **The key on your card** — scoped to the workshop's model project and nothing
  else, and it expires at the end of the day. It reaches a handful of models;
  `task llm:check` prints exactly which.

## Do we really need LiteLLM?

Honest answer: **for this workshop, no.** LibreChat speaks the OpenAI API
natively — point it straight at the provider and you could delete a whole
service. Be suspicious of anyone who tells you a gateway is free.

We keep it for two reasons that survive scrutiny, and one that doesn't:

1. **A control point — the strong one.** Budgets, rate limits and spend
   tracking have to live *somewhere*, and a gateway is the only place that sees
   every request from every client. You'll use this in a minute: mint a key
   capped at 50 cents and watch the spend climb against it.
2. **Swappability — the one you'll take home.** Clients ask for a model name;
   the gateway decides what actually serves it. Changing provider becomes a
   config edit instead of a change to every application.
3. **One place for the credential — weaker than it sounds here.** True, your key
   sits in LiteLLM's environment and clients get a master key instead. But with
   one laptop and one user, you've moved the secret, not protected it. This
   argument earns its keep when there are many clients and many people, not
   when there's one of each.

That's the trade-off: one more container, in exchange for a place to put
controls. If you rebuild this at home for yourself alone, skipping it is a
defensible choice.

## Bring it up

Copy `.env.example` to `.env` if you haven't, then put the key from your card
into it as `LLM_API_KEY`.

The key is about 170 characters, so rather than typing it, scan the QR code on
your card. Run `task up:docs` if it isn't already running, open
**[http://localhost:4321/creds](http://localhost:4321/creds)**, click *Start
camera*, hold the card up, and copy the two lines it decodes into `.env`.

That page is worth a second's thought, because it is doing something you should
normally refuse to do — putting a live credential through a web page. It is
safe here for reasons that are all structural, not promises: it is served from
*your* laptop, the QR is decoded in your browser by a JavaScript library
vendored into this repo rather than fetched from a CDN, and the page makes no
network requests at all. Pull your network cable out and it still works. If
someone hands you a scanner page that doesn't meet that bar, type the key
instead.

Check the key before starting anything — this tells you which models you can
reach, and catches a mistyped paste before it becomes a confusing error later:

```bash
task llm:check
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
  -d '{"models":["workshop-default"],"max_budget":0.50,"key_alias":"mine"}'
```

  Use the `sk-...` it returns instead of `sk-workshop` and the dashboard will
  track every call against that budget. That is the whole argument for running a
  gateway, in one exercise.
- LiteLLM speaks OpenAI's API on port 4000. Prove it from the terminal:

```bash
curl -s http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-workshop" -H "Content-Type: application/json" \
  -d '{"model": "workshop-default", "messages": [{"role": "user", "content": "ping"}]}'
```

That same call, made by LibreChat on your behalf, is everything the chat UI
is. Open a new chat, pick **Workshop Models → workshop-default**, and say hello.

`workshop-default` is an alias, not a model. The picker lists every model your
key can reach — the gateway asks the provider at startup rather than keeping a
list in this repo — and the alias points at one that is good at calling tools,
which Steps 4 and 5 depend on. Try the others for chat; expect the tool steps to
want the default.

## Take this home

The swappability argument above is worth more than a paragraph, so here is the
whole of it. To put a different provider behind the same endpoint your tools
already speak, add one entry to `litellm/config.yaml`:

```yaml
  - model_name: my-model
    litellm_params:
      model: anthropic/claude-sonnet-5     # or vertex_ai/..., azure/..., ollama/...
      api_key: os.environ/MY_PROVIDER_KEY
```

Nothing else changes. LibreChat, your scripts, and anything else that speaks the
OpenAI API keep working against `http://localhost:4000/v1`. That is the entire
trick, and it is why this one container is worth knowing about: you now have
everything you need to do this in your own account, with your own key, against
whatever provider you like.

## What the model can't do yet

Ask it: *"How many telemetry samples are in the readings table?"*

It will make something up, or admit it has no idea — it has no connection to
our warehouse whatsoever. The model only knows what's in its prompt. Giving
it a way to *find out* — tools it can call, with the results fed back into
the conversation — is exactly what MCP standardizes.

Next: [Step 4 — Build an MCP server for Trino](04-mcp-server.md)
