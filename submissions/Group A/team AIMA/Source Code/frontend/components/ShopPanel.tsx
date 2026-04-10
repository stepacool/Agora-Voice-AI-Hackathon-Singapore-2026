"use client"

import { useEffect, useState } from "react"

type Product = { sku: string; name: string; price: number }
type CartLine = { sku: string; qty: number }
type ShopState = { cart: CartLine[]; current_page: string }
type ShopResponse = { state: ShopState; products: Product[] }

const SHOP_URL = process.env.NEXT_PUBLIC_SHOP_URL || "http://localhost:8000"

export function ShopPanel() {
  const [data, setData] = useState<ShopResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const fetchState = async () => {
      try {
        const res = await fetch(`${SHOP_URL}/shop/state`, { cache: "no-store" })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const json: ShopResponse = await res.json()
        if (!cancelled) {
          setData(json)
          setError(null)
        }
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      }
    }

    fetchState()
    const id = setInterval(fetchState, 1000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  const reset = async () => {
    await fetch(`${SHOP_URL}/shop/reset`, { method: "POST" })
  }

  if (error && !data) {
    return (
      <div className="p-6 text-sm text-red-500">
        Cannot reach shop server at {SHOP_URL}
        <br />
        {error}
      </div>
    )
  }

  if (!data) {
    return <div className="p-6 text-sm text-gray-500">Loading shop…</div>
  }

  const { state, products } = data
  const productMap = Object.fromEntries(products.map((p) => [p.sku, p]))
  const total = state.cart.reduce((sum, line) => {
    const p = productMap[line.sku]
    return sum + (p ? p.price * line.qty : 0)
  }, 0)

  return (
    <div className="flex flex-col gap-6 p-6 h-full overflow-auto">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Voice Shop</h1>
        <div className="flex items-center gap-3">
          <span className="rounded-full border px-3 py-1 text-xs uppercase tracking-wide">
            page: {state.current_page}
          </span>
          <button
            onClick={reset}
            className="rounded-md border px-3 py-1 text-xs hover:bg-gray-100 dark:hover:bg-gray-800"
          >
            reset
          </button>
        </div>
      </div>

      <section>
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-gray-500">
          Products
        </h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {products.map((p) => (
            <div
              key={p.sku}
              className="rounded-lg border p-3 transition-colors hover:border-gray-400"
            >
              <div className="text-sm font-medium">{p.name}</div>
              <div className="text-xs text-gray-500">{p.sku}</div>
              <div className="mt-2 text-sm">${p.price.toFixed(2)}</div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-gray-500">
          Cart
        </h2>
        {state.cart.length === 0 ? (
          <div className="rounded-lg border border-dashed p-6 text-center text-sm text-gray-500">
            Cart is empty — try saying &ldquo;add a ceramic mug to my cart&rdquo;
          </div>
        ) : (
          <div className="rounded-lg border">
            {state.cart.map((line) => {
              const p = productMap[line.sku]
              return (
                <div
                  key={line.sku}
                  className="flex items-center justify-between border-b px-4 py-3 last:border-b-0"
                >
                  <div>
                    <div className="text-sm font-medium">{p?.name ?? line.sku}</div>
                    <div className="text-xs text-gray-500">qty {line.qty}</div>
                  </div>
                  <div className="text-sm">
                    ${((p?.price ?? 0) * line.qty).toFixed(2)}
                  </div>
                </div>
              )
            })}
            <div className="flex items-center justify-between px-4 py-3 font-medium">
              <span>Total</span>
              <span>${total.toFixed(2)}</span>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
