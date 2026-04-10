"""
Custom LLM server for Agora ConvoAI — voice-controlled pseudo-shop.

Sits between Agora and OpenAI:
  Agora ──POST /chat/completions──> this server ──> OpenAI (with tools)
                                          │
                                          └──> mutates STATE_PATH JSON

Frontend polls GET /shop/state every 1s to mirror the JSON state.
"""

import json
import os
import time
import uuid
from copy import deepcopy
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from openai import OpenAI

# ─── Config ───────────────────────────────────────────────────────────────
STATE_PATH = os.environ.get("STATE_PATH", "./shop_state.json")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
PORT = int(os.environ.get("PORT", "8000"))

PRODUCTS = [
    {"sku": "shirt-blue",  "name": "Blue T-Shirt",  "price": 19.99},
    {"sku": "shirt-red",   "name": "Red T-Shirt",   "price": 19.99},
    {"sku": "mug-ceramic", "name": "Ceramic Mug",   "price":  9.50},
    {"sku": "cap-black",   "name": "Black Cap",     "price": 14.00},
    {"sku": "socks-wool",  "name": "Wool Socks",    "price": 12.00},
    {"sku": "tote-canvas", "name": "Canvas Tote",   "price": 16.50},
]

VALID_PAGES = ["home", "products", "cart", "checkout"]

DEFAULT_STATE: dict[str, Any] = {"cart": [], "current_page": "home"}

SKUS = [p["sku"] for p in PRODUCTS]


# ─── State helpers ────────────────────────────────────────────────────────
def load_state() -> dict[str, Any]:
    if not os.path.exists(STATE_PATH):
        return deepcopy(DEFAULT_STATE)
    with open(STATE_PATH, "r") as f:
        return json.load(f)


def save_state(state: dict[str, Any]) -> None:
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_PATH)


def product_by_sku(sku: str) -> dict | None:
    for p in PRODUCTS:
        if p["sku"] == sku:
            return p
    return None


# ─── Tool implementations ─────────────────────────────────────────────────
def tool_add_to_cart(sku: str, quantity: int = 1) -> dict:
    if sku not in SKUS:
        return {"ok": False, "error": f"unknown sku '{sku}'. valid: {SKUS}"}
    if quantity < 1:
        return {"ok": False, "error": "quantity must be >= 1"}
    state = load_state()
    for line in state["cart"]:
        if line["sku"] == sku:
            line["qty"] += quantity
            break
    else:
        state["cart"].append({"sku": sku, "qty": quantity})
    save_state(state)
    name = product_by_sku(sku)["name"]
    return {"ok": True, "message": f"added {quantity} × {name}", "cart": state["cart"]}


def tool_remove_from_cart(sku: str) -> dict:
    state = load_state()
    before = len(state["cart"])
    state["cart"] = [l for l in state["cart"] if l["sku"] != sku]
    if len(state["cart"]) == before:
        return {"ok": False, "error": f"'{sku}' was not in the cart"}
    save_state(state)
    return {"ok": True, "message": f"removed {sku}", "cart": state["cart"]}


def tool_clear_cart() -> dict:
    state = load_state()
    state["cart"] = []
    save_state(state)
    return {"ok": True, "message": "cart cleared"}


def tool_navigate(page: str) -> dict:
    if page not in VALID_PAGES:
        return {"ok": False, "error": f"unknown page '{page}'. valid: {VALID_PAGES}"}
    state = load_state()
    state["current_page"] = page
    save_state(state)
    return {"ok": True, "message": f"navigated to {page}"}


TOOL_FUNCS = {
    "add_to_cart": tool_add_to_cart,
    "remove_from_cart": tool_remove_from_cart,
    "clear_cart": tool_clear_cart,
    "navigate": tool_navigate,
}


# ─── OpenAI tool schemas ──────────────────────────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_to_cart",
            "description": "Add a product to the shopping cart by SKU.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string", "enum": SKUS, "description": "Product SKU"},
                    "quantity": {"type": "integer", "minimum": 1, "default": 1},
                },
                "required": ["sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_from_cart",
            "description": "Remove a product line from the shopping cart by SKU.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string", "enum": SKUS},
                },
                "required": ["sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_cart",
            "description": "Empty the entire shopping cart.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate",
            "description": "Navigate the shop UI to a specific page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "page": {"type": "string", "enum": VALID_PAGES},
                },
                "required": ["page"],
            },
        },
    },
]


# ─── Helpers ──────────────────────────────────────────────────────────────
def build_context_system_message() -> dict:
    state = load_state()
    catalog_lines = [f"  - {p['sku']}: {p['name']} (${p['price']:.2f})" for p in PRODUCTS]
    cart_lines = (
        [f"  - {l['sku']} × {l['qty']}" for l in state["cart"]]
        if state["cart"]
        else ["  (empty)"]
    )
    content = (
        "You are a voice shopping assistant. Use the provided tools to add/remove items, "
        "clear the cart, or navigate pages. Do not just describe what you'd do — actually call the tools. "
        "Keep spoken replies under 15 words.\n\n"
        f"Catalog:\n" + "\n".join(catalog_lines) + "\n\n"
        f"Current page: {state['current_page']}\n"
        f"Current cart:\n" + "\n".join(cart_lines)
    )
    return {"role": "system", "content": content}


def sse_chunk(text: str, model: str, finish: str | None = None) -> str:
    """Build one OpenAI-format SSE chat.completion.chunk frame."""
    chunk = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": text} if text else {},
                "finish_reason": finish,
            }
        ],
    }
    return f"data: {json.dumps(chunk)}\n\n"


def fake_stream(text: str, model: str):
    # initial role frame
    role_chunk = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
    }
    yield f"data: {json.dumps(role_chunk)}\n\n"
    # body in ~20 char chunks
    step = 20
    for i in range(0, len(text), step):
        yield sse_chunk(text[i : i + step], model)
    yield sse_chunk("", model, finish="stop")
    yield "data: [DONE]\n\n"


# ─── FastAPI app ──────────────────────────────────────────────────────────
app = FastAPI(title="Voice Shop Custom LLM")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_client: OpenAI | None = None


def openai_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/shop/state")
def shop_state():
    return {"state": load_state(), "products": PRODUCTS}


@app.post("/shop/reset")
def shop_reset():
    save_state(deepcopy(DEFAULT_STATE))
    return {"ok": True, "state": load_state()}


@app.post("/register-agent")
async def register_agent(req: Request):
    body = await req.json()
    print(f"[register-agent] channel={body.get('channel')} agent_id={body.get('agent_id')}")
    return {"ok": True}


@app.post("/unregister-agent")
async def unregister_agent(req: Request):
    body = await req.json()
    print(f"[unregister-agent] channel={body.get('channel')} agent_id={body.get('agent_id')}")
    return {"ok": True}


@app.post("/chat/completions")
async def chat_completions(req: Request):
    body = await req.json()
    incoming_messages = body.get("messages", [])
    model = body.get("model") or OPENAI_MODEL

    # Prepend live shop context (replaces any system message Agora sent)
    messages = [build_context_system_message()] + [
        m for m in incoming_messages if m.get("role") != "system"
    ]

    client = openai_client()

    # Agentic loop
    final_text = ""
    for _ in range(5):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        msg = resp.choices[0].message

        if msg.tool_calls:
            # Append assistant message with tool_calls
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )
            # Execute each tool call
            for tc in msg.tool_calls:
                fn = TOOL_FUNCS.get(tc.function.name)
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if fn is None:
                    result = {"ok": False, "error": f"unknown tool {tc.function.name}"}
                else:
                    print(f"[tool] {tc.function.name}({args})")
                    result = fn(**args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result),
                    }
                )
            continue  # loop again so model can produce final text

        final_text = msg.content or ""
        break

    if not final_text:
        final_text = "Done."

    return StreamingResponse(
        fake_stream(final_text, model),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
