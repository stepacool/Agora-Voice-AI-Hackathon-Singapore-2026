# Custom LLM — Voice Shop

FastAPI server that sits between Agora ConvoAI and OpenAI. It exposes an
OpenAI-compatible `/chat/completions` endpoint with shop tools wired in
(`add_to_cart`, `remove_from_cart`, `clear_cart`, `navigate`). Tool calls
mutate a JSON state file the frontend polls.

## Run

```bash
cd custom-llm
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export OPENAI_API_KEY=sk-...
# Optional:
# export STATE_PATH=./shop_state.json
# export OPENAI_MODEL=gpt-4o-mini
# export PORT=8000

python app.py
# or: uvicorn app:app --port 8000 --reload
```

## Expose to Agora (cloudflared)

Agora's cloud must reach `/chat/completions`. Use a tunnel:

```bash
cloudflared tunnel --url http://localhost:8000
```

Copy the `https://<random>.trycloudflare.com` URL and put it in
`backend/.env`:

```
VOICE_LLM_VENDOR=custom
VOICE_LLM_URL=https://<random>.trycloudflare.com/chat/completions
VOICE_LLM_STYLE=openai
```

## Endpoints

| Method | Path                 | Purpose                              |
|--------|----------------------|--------------------------------------|
| POST   | /chat/completions    | Agora-facing OpenAI-compatible chat  |
| GET    | /shop/state          | Frontend polls every 1s              |
| POST   | /shop/reset          | Reset cart + page to defaults        |
| POST   | /register-agent      | No-op (Agora backend pings this)     |
| POST   | /unregister-agent    | No-op                                |
| GET    | /health              | Health check                         |

## Smoke test

```bash
# Drive the LLM directly
curl -N -X POST http://localhost:8000/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"add two blue shirts and a ceramic mug"}]}'

# Check state mutated
curl http://localhost:8000/shop/state

# Reset
curl -X POST http://localhost:8000/shop/reset
```
