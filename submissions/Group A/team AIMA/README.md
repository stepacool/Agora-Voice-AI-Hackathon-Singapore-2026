DEMO video: https://www.loom.com/share/098d535ab0f145f7b0f7c87a87b01390

# Voice Shop — Agora ConvoAI Hackathon (Team AIMA)

A pseudo e-commerce storefront you control entirely with your voice. Tell the
agent "add two blue shirts to my cart" or "take me to checkout" and the UI
updates within ~1 second. Built on Agora's Conversational AI Engine + RTC SDK
with a custom LLM server in the middle that performs tool calling against a
JSON state file.

## What it does

- Speak to a voice agent in the browser
- The agent has tools: `add_to_cart`, `remove_from_cart`, `clear_cart`, `navigate`
- Tool calls mutate a single JSON file (`shop_state.json`)
- The frontend polls that state every second and re-renders the cart, product
  grid, and current page badge

The whole point of the project is to demonstrate **voice-driven app state
mutation** through Agora's ConvoAI custom LLM hook — not just a talking head.

## Architecture

```
┌──────────────┐  RTC audio   ┌─────────────────┐   tool calls    ┌───────────┐
│              │ ◄─────────►  │                 │ ──────────────► │           │
│   Browser    │              │  Agora ConvoAI  │                 │  OpenAI   │
│  (Next.js)   │              │     (cloud)     │ ◄────────────── │           │
│              │              │                 │   completions   └───────────┘
└──────────────┘              └────────┬────────┘
       │                               │ POST /chat/completions
       │ poll GET /shop/state          │
       │ every 1s                      ▼
       │                      ┌─────────────────┐
       │                      │   custom-llm    │
       └────────────────────► │   (FastAPI)     │
                              │                 │
                              │  shop_state.json│
                              └─────────────────┘
                                       ▲
                                       │ POST /start-agent (once per session)
                                       │
                              ┌─────────────────┐
                              │  backend (Flask)│
                              │  token + agent  │
                              │  provisioning   │
                              └─────────────────┘
```

Four processes during a demo:

| Process | Purpose | Port |
|---|---|---|
| `backend/local_server.py` (Flask) | Generates RTC tokens, POSTs the agent spec to Agora | 8082 |
| `custom-llm/app.py` (FastAPI) | OpenAI-compatible `/chat/completions` with shop tools, plus `/shop/state` for the frontend | 8000 |
| `frontend` (Next.js) | UI: voice client + shop panel | 3000 |
| `cloudflared tunnel` | Public HTTPS for the custom LLM (Agora's cloud calls it from the internet) | — |

## How Agora is integrated

### Conversational AI Engine

The Flask backend (`backend/core/agent.py`) builds the agent payload and POSTs
it to `https://api.agora.io/api/conversational-ai-agent/v2/projects/<APP_ID>/join`
when the user clicks "connect". Key choices in the payload:

- `llm.vendor = "custom"` and `llm.url` points at the cloudflared tunnel for
  `custom-llm/app.py`. Agora's cloud will dial this URL for every LLM
  completion the agent needs.
- `llm.style = "openai"` so Agora speaks the OpenAI Chat Completions wire
  format with our server.
- `tts.vendor = "elevenlabs"` for synthesis (`flash_v2_5` model).
- `asr.vendor = "ares"` (Agora's built-in ASR, no extra key required).
- `turn_detection.end_of_speech.mode = "semantic"` (AIVAD) so the agent waits
  for true end-of-thought, not just silence.
- `advanced_features.enable_rtm = true` so transcripts and agent messages flow
  back to the browser over RTM.
- The `llm.params` block carries `channel`, `app_id`, `subscriber_token`,
  `rtm_token`, and `rtm_uid` so the custom LLM could publish RTM messages or
  subscribe to audio if it wanted to (we don't, polling is simpler).

After Agora returns `agent_id`, the Flask backend asynchronously POSTs to
`/register-agent` on the custom LLM (no-op for us, kept so the integration
contract is honoured).

### RTC SDK

The frontend uses `agora-rtc-sdk-ng` (v4) and `agora-rtm` (v2). The connection
flow lives in `frontend/hooks/useAgoraVoiceClient.ts`:

1. `GET /start-agent` → Flask returns `{appid, channel, token, uid, agent: {uid}}`
2. `client.join(appid, channel, token, uid)` — joins the RTC channel as the
   user
3. `AgoraRTC.createMicrophoneAudioTrack()` + `client.publish([track])` — push
   mic audio
4. The agent (`agent.uid = 100`) joins the same channel from Agora's cloud,
   publishes its TTS audio, which the browser auto-subscribes to
5. RTM client subscribes to the channel for live transcripts and agent text
6. On hangup: `GET /hangup-agent?agent_id=...` tells Agora to terminate the
   agent, then the browser leaves the channel

### Custom LLM tool-calling loop

`custom-llm/app.py` exposes `POST /chat/completions` (OpenAI-compatible). On
every call it:

1. Drops any system message Agora forwarded and prepends a fresh system
   message containing the **live product catalog and current cart**, so the
   model always has up-to-date context regardless of what's in the chat
   history.
2. Calls `openai.chat.completions.create(..., tools=TOOLS, tool_choice="auto")`
   non-streaming.
3. If the response has `tool_calls`, executes each one against
   `shop_state.json` (atomic write via tmp + `os.replace`), appends the tool
   results, and loops.
4. When the model finally produces text, fake-streams it back to Agora as
   OpenAI-format SSE chunks (`data: {...}\n\n`, terminated with
   `data: [DONE]\n\n`).

The four tools are:

| Tool | Effect on state |
|---|---|
| `add_to_cart(sku, quantity)` | Increments existing line or appends new |
| `remove_from_cart(sku)` | Removes the line |
| `clear_cart()` | Empties cart |
| `navigate(page)` | Sets `current_page` to one of `home/products/cart/checkout` |

SKUs are constrained to an enum drawn from the product catalog so the model
can't hallucinate ids.

## Setup

### 0. Prerequisites

- Python 3.11+ (3.13 tested)
- Node 20+
- An Agora project with **Conversational AI Agent** enabled (Console → your
  project → enable the product)
- An OpenAI API key
- An ElevenLabs API key + voice id (or swap `VOICE_TTS_VENDOR` for OpenAI/Cartesia/Rime)
- `cloudflared` installed (`brew install cloudflared`)

### 1. Backend (Flask — token + agent provisioning)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-local.txt
cp .env.example .env
# Fill in VOICE_APP_ID, VOICE_APP_CERTIFICATE, VOICE_TTS_KEY, VOICE_TTS_VOICE_ID
python3 -u local_server.py     # http://localhost:8082
```

If you're on macOS Python 3.13 and see `SSL: CERTIFICATE_VERIFY_FAILED`, run
`/Applications/Python\ 3.13/Install\ Certificates.command` once.

### 2. Custom LLM (FastAPI — tool calling + shop state)

```bash
cd custom-llm
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
echo "OPENAI_API_KEY=sk-..." > .env       # loaded by python-dotenv
python app.py                              # http://localhost:8000
```

Optional env vars: `STATE_PATH` (default `./shop_state.json`), `OPENAI_MODEL`
(default `gpt-4o-mini`), `PORT` (default `8000`).

### 3. Tunnel (so Agora's cloud can reach the custom LLM)

```bash
cloudflared tunnel --url http://localhost:8000
# copy the https://<random>.trycloudflare.com URL it prints
```

Paste it into `backend/.env` — **including the `/chat/completions` path**:

```
VOICE_LLM_VENDOR=custom
VOICE_LLM_STYLE=openai
VOICE_LLM_URL=https://<random>.trycloudflare.com/chat/completions
```

Restart the Flask backend after editing `.env`.

### 4. Frontend (Next.js)

```bash
cd frontend
npm install
echo "NEXT_PUBLIC_SHOP_URL=http://localhost:8000" > .env.local
npm run dev                                # http://localhost:3000
```

Open `http://localhost:3000`, click connect, allow microphone access, and try:

- "Add a ceramic mug to my cart"
- "Add two blue shirts"
- "Take me to the cart page"
- "Clear my cart"
- "Go to checkout"

The right-hand panel polls `/shop/state` every second, so changes appear ~1s
after the agent's voice confirmation.

### Smoke testing the LLM without voice

```bash
curl -N -X POST http://localhost:8000/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"add two blue shirts"}]}'

curl http://localhost:8000/shop/state
curl -X POST http://localhost:8000/shop/reset
```

## Project layout

```
Source Code/
├── backend/                      # Flask: token + Agora provisioning
│   ├── local_server.py
│   └── core/
│       ├── agent.py              # Agora ConvoAI payload builder
│       ├── tokens.py             # v007 RTC + RTM tokens
│       └── config.py             # Profile-prefixed env vars
│
├── custom-llm/                   # FastAPI: tool-calling LLM proxy
│   ├── app.py                    # All logic — tools, state, /chat/completions
│   ├── requirements.txt
│   └── README.md
│
├── frontend/                     # Next.js 15 + Tailwind 4
│   ├── app/page.tsx              # Side-by-side VoiceClient + ShopPanel
│   ├── components/
│   │   ├── VoiceClient.tsx       # Existing Agora boilerplate UI
│   │   └── ShopPanel.tsx         # Polls /shop/state, renders cart + grid
│   └── hooks/
│       └── useAgoraVoiceClient.ts  # RTC + RTM connection logic
│
└── README.md                     # this file
```

## Known limitations

- **Single user.** State is one JSON file on disk. No sessions, no auth, no
  isolation. Multiple users would clobber each other's carts.
- **No persistence beyond the JSON file.** Restart `custom-llm/app.py` and the
  cart is whatever was last on disk. Restart with `shop_state.json` deleted
  and you're back to the default (empty cart, home page).
- **1-second polling, not push.** The frontend polls instead of subscribing to
  RTM messages from the custom LLM. There's a ~1s lag between tool execution
  and UI update. Could be replaced with RTM push (the custom LLM already
  receives an `rtm_token` in `llm.params`) but polling is simpler for a
  hackathon.
- **Cloudflare Quick Tunnels rotate URLs.** Every restart of `cloudflared
  tunnel --url ...` gives a new hostname, which means re-pasting into
  `backend/.env` and restarting Flask. A named tunnel or `ngrok` with a
  reserved domain fixes this for production.
- **Fake streaming.** The custom LLM does the tool-calling loop synchronously
  (non-streaming) and only streams the final text response in 20-character
  chunks. Real OpenAI streaming with mid-stream tool-call parsing would feel
  marginally more responsive on long answers but adds a lot of code.
- **Hangup doesn't carry the profile.** The frontend hits `/hangup-agent`
  without `&profile=VOICE`, so the backend's best-effort `/unregister-agent`
  call goes to the default (OpenAI) URL and 404s. Harmless — the agent is
  still terminated correctly on Agora's side.
- **Shop UI is voice-only by design.** Products and reset are clickable but
  there are no add-to-cart buttons. The whole point is to drive the cart with
  speech.
- **Mobile layout is unstyled.** Desktop side-by-side only.
- **Secrets in `.env`.** Hackathon-grade. Don't commit them; rotate any keys
  that ever ended up in a screenshot or log.
- **No tests.** The original Agora boilerplate ships pytest tests for the
  Flask layer (`backend/tests/`) and they still pass, but the custom LLM and
  ShopPanel are uncovered.

## Credit

- Built on the Agora ConvoAI hackathon starter (`backend/`, `frontend/`).
- Adds `custom-llm/` and `frontend/components/ShopPanel.tsx`; minor edits to
  `frontend/app/page.tsx` and `backend/.env`.
