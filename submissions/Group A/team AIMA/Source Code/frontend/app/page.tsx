"use client"

import dynamic from "next/dynamic"
import { ShopPanel } from "@/components/ShopPanel"

const VoiceClient = dynamic(
  () => import("@/components/VoiceClient").then((mod) => ({ default: mod.VoiceClient })),
  {
    ssr: false,
  }
)

export default function Home() {
  return (
    <div className="flex h-screen w-screen">
      <div className="w-1/2 border-r overflow-hidden">
        <VoiceClient />
      </div>
      <div className="w-1/2 overflow-auto">
        <ShopPanel />
      </div>
    </div>
  )
}
