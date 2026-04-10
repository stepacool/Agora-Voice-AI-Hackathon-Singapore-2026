"""
Custom LLM server for Agora ConvoAI — voice-controlled pseudo-shop.

Sits between Agora and OpenAI:
  Agora ──POST /chat/completions──> this server ──> OpenAI (with tools)
                                          │
                                          └──> mutates STATE_PATH JSON

Frontend polls GET /shop/state every 1s to mirror the JSON state.
"""
from dotenv import load_dotenv
load_dotenv(override=True)  # Load .env file before importing core modules, override existing env vars

import json
import os
import time
import uuid
from copy import deepcopy
from typing import Any
from urllib.parse import quote_plus

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
    # Apparel
    {"sku": "shirt-blue",     "name": "Blue T-Shirt",       "price": 19.99, "category": "apparel",
     "description": "Soft cotton crew-neck tee in classic blue."},
    {"sku": "shirt-red",      "name": "Red T-Shirt",        "price": 19.99, "category": "apparel",
     "description": "Soft cotton crew-neck tee in bold red."},
    {"sku": "shirt-white",    "name": "White T-Shirt",      "price": 18.99, "category": "apparel",
     "description": "Plain white cotton tee, an everyday staple."},
    {"sku": "shirt-black",    "name": "Black T-Shirt",      "price": 19.99, "category": "apparel",
     "description": "Classic black cotton tee."},
    {"sku": "hoodie-grey",    "name": "Grey Hoodie",        "price": 49.00, "category": "apparel",
     "description": "Heavyweight pullover hoodie in heather grey."},
    {"sku": "hoodie-navy",    "name": "Navy Hoodie",        "price": 49.00, "category": "apparel",
     "description": "Pullover hoodie in deep navy with kangaroo pocket."},
    {"sku": "sweater-knit",   "name": "Knit Sweater",       "price": 65.00, "category": "apparel",
     "description": "Chunky cable-knit sweater in oat."},
    {"sku": "jacket-denim",   "name": "Denim Jacket",       "price": 89.00, "category": "apparel",
     "description": "Classic blue denim jacket with button front."},
    {"sku": "pants-chino",    "name": "Khaki Chinos",       "price": 55.00, "category": "apparel",
     "description": "Straight-fit cotton chinos in khaki."},
    {"sku": "pants-jogger",   "name": "Black Joggers",      "price": 45.00, "category": "apparel",
     "description": "Comfortable black fleece joggers with elastic cuffs."},

    # Footwear
    {"sku": "shoes-sneaker",  "name": "White Sneakers",     "price": 75.00, "category": "footwear",
     "description": "Low-top white leather sneakers."},
    {"sku": "shoes-running",  "name": "Running Shoes",      "price": 95.00, "category": "footwear",
     "description": "Lightweight mesh running shoes with cushioned sole."},
    {"sku": "shoes-boot",     "name": "Leather Boots",      "price": 130.00, "category": "footwear",
     "description": "Brown leather ankle boots, lace-up."},
    {"sku": "shoes-sandal",   "name": "Tan Sandals",        "price": 35.00, "category": "footwear",
     "description": "Open-toe tan leather sandals."},
    {"sku": "shoes-slipper",  "name": "Wool Slippers",      "price": 28.00, "category": "footwear",
     "description": "Cozy felted wool house slippers."},

    # Accessories
    {"sku": "cap-black",      "name": "Black Cap",          "price": 14.00, "category": "accessories",
     "description": "Adjustable cotton baseball cap in black."},
    {"sku": "cap-white",      "name": "White Cap",          "price": 14.00, "category": "accessories",
     "description": "Adjustable cotton baseball cap in white."},
    {"sku": "beanie-grey",    "name": "Grey Beanie",        "price": 18.00, "category": "accessories",
     "description": "Ribbed knit beanie in heather grey."},
    {"sku": "scarf-wool",     "name": "Wool Scarf",         "price": 32.00, "category": "accessories",
     "description": "Soft wool scarf in plaid pattern."},
    {"sku": "belt-leather",   "name": "Leather Belt",       "price": 38.00, "category": "accessories",
     "description": "Brown full-grain leather belt with brass buckle."},
    {"sku": "gloves-knit",    "name": "Knit Gloves",        "price": 22.00, "category": "accessories",
     "description": "Touchscreen-friendly knit winter gloves."},
    {"sku": "sunglasses",     "name": "Sunglasses",         "price": 45.00, "category": "accessories",
     "description": "Black frame UV400 sunglasses."},
    {"sku": "watch-analog",   "name": "Analog Watch",       "price": 120.00, "category": "accessories",
     "description": "Minimalist stainless steel analog wristwatch."},
    {"sku": "socks-wool",     "name": "Wool Socks",         "price": 12.00, "category": "accessories",
     "description": "Warm merino wool crew socks."},

    # Home & Kitchen
    {"sku": "mug-ceramic",    "name": "Ceramic Mug",        "price":  9.50, "category": "home",
     "description": "12oz white ceramic coffee mug."},
    {"sku": "mug-enamel",     "name": "Enamel Camp Mug",    "price": 12.00, "category": "home",
     "description": "Speckled enamel camping mug, 14oz."},
    {"sku": "bottle-water",   "name": "Water Bottle",       "price": 24.00, "category": "home",
     "description": "Insulated 24oz stainless steel water bottle."},
    {"sku": "thermos",        "name": "Thermos",            "price": 32.00, "category": "home",
     "description": "16oz vacuum-insulated thermos for hot coffee or tea."},
    {"sku": "plate-set",      "name": "Plate Set",          "price": 48.00, "category": "home",
     "description": "Set of four stoneware dinner plates."},
    {"sku": "bowl-soup",      "name": "Soup Bowl",          "price": 11.00, "category": "home",
     "description": "Deep ceramic soup bowl, dishwasher safe."},
    {"sku": "candle-vanilla", "name": "Vanilla Candle",     "price": 16.00, "category": "home",
     "description": "Hand-poured soy wax candle, vanilla scent."},
    {"sku": "candle-pine",    "name": "Pine Candle",        "price": 16.00, "category": "home",
     "description": "Hand-poured soy candle with fresh pine scent."},
    {"sku": "vase-glass",     "name": "Glass Vase",         "price": 28.00, "category": "home",
     "description": "Clear cylindrical glass flower vase."},
    {"sku": "lamp-desk",      "name": "Desk Lamp",          "price": 55.00, "category": "home",
     "description": "Adjustable LED desk lamp with USB port."},

    # Bags
    {"sku": "tote-canvas",    "name": "Canvas Tote",        "price": 16.50, "category": "bags",
     "description": "Sturdy unbleached canvas shoulder tote."},
    {"sku": "backpack",       "name": "Backpack",           "price": 65.00, "category": "bags",
     "description": "20L water-resistant daypack with laptop sleeve."},
    {"sku": "duffel",         "name": "Duffel Bag",         "price": 78.00, "category": "bags",
     "description": "Heavy canvas duffel for weekend trips."},
    {"sku": "messenger",      "name": "Messenger Bag",      "price": 58.00, "category": "bags",
     "description": "Crossbody messenger bag with padded laptop section."},
    {"sku": "wallet-bifold",  "name": "Bifold Wallet",      "price": 38.00, "category": "bags",
     "description": "Slim leather bifold wallet, six card slots."},

    # Tech
    {"sku": "headphones",     "name": "Headphones",         "price": 149.00, "category": "tech",
     "description": "Over-ear wireless noise-cancelling headphones."},
    {"sku": "earbuds",        "name": "Wireless Earbuds",   "price": 89.00, "category": "tech",
     "description": "True wireless in-ear earbuds with charging case."},
    {"sku": "speaker-bt",     "name": "Bluetooth Speaker",  "price": 55.00, "category": "tech",
     "description": "Portable waterproof Bluetooth speaker."},
    {"sku": "keyboard",       "name": "Mechanical Keyboard","price": 110.00, "category": "tech",
     "description": "Tenkeyless mechanical keyboard with brown switches."},
    {"sku": "mouse-wireless", "name": "Wireless Mouse",     "price": 35.00, "category": "tech",
     "description": "Ergonomic wireless mouse with USB-C charging."},
    {"sku": "cable-usbc",     "name": "USB-C Cable",        "price":  9.00, "category": "tech",
     "description": "1m braided USB-C to USB-C charging cable."},

    # Stationery
    {"sku": "notebook",       "name": "Notebook",           "price": 14.00, "category": "stationery",
     "description": "Hardcover dotted notebook, 192 pages."},
    {"sku": "journal",        "name": "Leather Journal",    "price": 28.00, "category": "stationery",
     "description": "Refillable leather-bound lined journal."},
    {"sku": "pen-fountain",   "name": "Fountain Pen",       "price": 42.00, "category": "stationery",
     "description": "Brass fountain pen with medium nib."},
    {"sku": "stickers",       "name": "Sticker Pack",       "price":  6.00, "category": "stationery",
     "description": "Pack of ten vinyl waterproof stickers."},
    {"sku": "planner",        "name": "Daily Planner",      "price": 22.00, "category": "stationery",
     "description": "Undated daily planner with weekly spreads."},
    {"sku": "pencils",        "name": "Pencil Set",         "price":  8.00, "category": "stationery",
     "description": "Set of twelve graphite drawing pencils."},
]

VALID_PAGES = ["home", "products", "cart", "checkout", "order_complete"]

# Real image assets that exist on disk in frontend/public/images/.
# Any SKU not listed here falls back to a placehold.co URL.
PRODUCT_IMAGES = {
    "shirt-blue":  "/images/shirt-blue.png",
    "shirt-red":   "/images/shirt-red.png",
    "cap-black":   "/images/cap-black.png",
    "mug-ceramic": "/images/mug-ceramic.png",
    "tote-canvas": "/images/tote-canvas.png",
    "socks-wool":  "/images/socks-wool.png",
}

DEFAULT_STATE: dict[str, Any] = {
    "cart": [],
    "current_page": "home",
    "last_order": None,
    "search": {"query": "", "skus": []},
}

SKUS = [p["sku"] for p in PRODUCTS]


# ─── State helpers ────────────────────────────────────────────────────────
def load_state() -> dict[str, Any]:
    if not os.path.exists(STATE_PATH):
        return deepcopy(DEFAULT_STATE)
    with open(STATE_PATH, "r") as f:
        state = json.load(f)
    # Backfill any missing keys for forward compat with older state files
    for k, v in DEFAULT_STATE.items():
        state.setdefault(k, deepcopy(v))
    return state


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


def with_placeholder_images(products: list[dict]) -> list[dict]:
    """Decorate products with placehold.co image URLs (computed, not stored)."""
    result = []
    for p in products:
        sku = p["sku"]
        if sku in PRODUCT_IMAGES:
            image_url = PRODUCT_IMAGES[sku]
        else:
            image_url = f"https://placehold.co/300x300/e5e7eb/374151?text={quote_plus(p['name'])}"
        result.append({**p, "image": image_url})
    return result


# ─── Tool implementations ─────────────────────────────────────────────────
def tool_add_to_cart(sku: str, quantity: int = 1) -> dict:
    if sku not in SKUS:
        return {"ok": False, "error": f"unknown sku '{sku}'"}
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
    state["search"] = {"query": "", "skus": []}
    save_state(state)
    return {"ok": True, "message": f"navigated to {page}"}


def tool_find_items(query: str) -> dict:
    """Free-text search across name, description, and category."""
    q = (query or "").lower().strip()
    if not q:
        return {"ok": False, "error": "query is empty"}
        
    import re
    raw_terms = re.findall(r'[\w\-]+', q)
    stop_words = {"a", "an", "the", "and", "or", "for", "with", "in", "on", "at", "to", "of", "is", "it", "my", "some", "i", "want", "looking", "show", "me"}
    
    terms = []
    for t in raw_terms:
        if t in stop_words:
            continue
        terms.append(t)
        # simplistic plural stripping
        if len(t) > 3 and t.endswith('s') and not t.endswith('ss'):
            terms.append(t[:-1])
            
    matches = []
    for p in PRODUCTS:
        haystack = f"{p['name']} {p['description']} {p.get('category', '')}".lower()
        if q in haystack or (terms and any(t in haystack for t in terms)):
            matches.append(
                {
                    "sku": p["sku"],
                    "name": p["name"],
                    "price": p["price"],
                    "description": p["description"],
                }
            )
            
    state = load_state()
    state["search"] = {"query": query, "skus": [m["sku"] for m in matches[:10]]}
    save_state(state)
    
    return {"ok": True, "count": len(matches), "matches": matches[:10]}


def tool_place_order() -> dict:
    state = load_state()
    if not state["cart"]:
        return {"ok": False, "error": "cart is empty — add items before placing an order"}
    total = 0.0
    for line in state["cart"]:
        p = product_by_sku(line["sku"])
        if p:
            total += p["price"] * line["qty"]
    state["last_order"] = {
        "items": list(state["cart"]),
        "total": round(total, 2),
        "ts": int(time.time()),
    }
    state["cart"] = []
    state["current_page"] = "order_complete"
    state["search"] = {"query": "", "skus": []}
    save_state(state)
    return {"ok": True, "message": "order placed", "total": state["last_order"]["total"]}


TOOL_FUNCS = {
    "add_to_cart": tool_add_to_cart,
    "remove_from_cart": tool_remove_from_cart,
    "clear_cart": tool_clear_cart,
    "navigate": tool_navigate,
    "find_items": tool_find_items,
    "place_order": tool_place_order,
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
    {
        "type": "function",
        "function": {
            "name": "find_items",
            "description": (
                "Search the product catalog by free-text query. Matches against the "
                "product name, description, and category. Use this whenever the user "
                "describes an item without giving an exact SKU."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Free-text search query, e.g. 'coffee mug', 'running shoes', 'something blue'.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "place_order",
            "description": (
                "Place the current order: snapshots the cart, clears it, and navigates "
                "to the order_complete page. Errors if the cart is empty."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# ─── Helpers ──────────────────────────────────────────────────────────────
def build_context_system_message() -> dict:
    state = load_state()
    catalog_lines = [f"  {p['sku']} — {p['name']} (${p['price']:.2f})" for p in PRODUCTS]
    cart_lines = (
        [f"  - {l['sku']} × {l['qty']}" for l in state["cart"]]
        if state["cart"]
        else ["  (empty)"]
    )
    content = (
        "You are a voice shopping assistant. Use the provided tools — never just describe "
        "what you would do; actually call them. When the user describes an item loosely "
        "(\"something for hot coffee\", \"running shoes\", \"a blue shirt\"), call "
        "`find_items` first to look it up, then `add_to_cart` with the SKU you found. "
        "When the user is ready to buy, call `place_order` (it both completes the order "
        "and switches the page). Pages: home, products, cart, checkout, order_complete. "
        "Keep spoken replies under 15 words.\n\n"
        f"Catalog ({len(PRODUCTS)} items):\n" + "\n".join(catalog_lines) + "\n\n"
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
    return {"state": load_state(), "products": with_placeholder_images(PRODUCTS)}


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
    for _ in range(6):
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
