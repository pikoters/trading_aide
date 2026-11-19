<script setup lang="ts">
// Embed TradingView's public chart widget; chart data is served by TradingView,
// not the Go API or the application's offline cache.
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

/** Ticker uses Yahoo-style suffixes; height is the rendered chart area in px. */
const props = defineProps<{ ticker: string; height: number }>()
const host = ref<HTMLDivElement | null>(null)
const loading = ref(true)
const failed = ref(false)
let loadTimer: ReturnType<typeof setTimeout> | undefined

function tradingViewSymbol(ticker: string) {
  /** Convert common Yahoo exchange suffixes to TradingView exchange symbols. */
  const normalized = ticker.trim().toUpperCase()
  const exchangeSuffixes: Record<string, string> = {
    '.L': 'LSE',
    '.PA': 'EURONEXT',
    '.AS': 'EURONEXT',
    '.DE': 'XETR',
    '.MI': 'MIL',
    '.MC': 'BME',
    '.SW': 'SIX',
    '.TO': 'TSX',
    '.AX': 'ASX',
    '.HK': 'HKEX',
    '.T': 'TSE',
    '.KS': 'KRX',
  }

  for (const [suffix, exchange] of Object.entries(exchangeSuffixes)) {
    if (normalized.endsWith(suffix)) {
      return `${exchange}:${normalized.slice(0, -suffix.length)}`
    }
  }
  return normalized
}

function renderWidget() {
  /** Rebuild the external iframe and update loading/failure state. */
  if (!host.value || !props.ticker) return
  if (loadTimer) clearTimeout(loadTimer)
  host.value.replaceChildren()
  loading.value = true
  failed.value = false

  const widgetURL = new URL('https://www.tradingview.com/widgetembed/')
  widgetURL.searchParams.set('symbol', tradingViewSymbol(props.ticker))
  widgetURL.searchParams.set('interval', 'D')
  widgetURL.searchParams.set('theme', 'light')
  widgetURL.searchParams.set('style', '1')
  widgetURL.searchParams.set('locale', 'en')
  widgetURL.searchParams.set('timezone', 'Etc/UTC')
  widgetURL.searchParams.set('allow_symbol_change', '1')
  widgetURL.searchParams.set('hide_top_toolbar', '0')
  widgetURL.searchParams.set('hide_side_toolbar', '0')
  widgetURL.searchParams.set('withdateranges', '1')
  widgetURL.searchParams.set('saveimage', '0')

  const iframe = document.createElement('iframe')
  iframe.title = `${props.ticker} daily chart on TradingView`
  iframe.src = widgetURL.toString()
  iframe.loading = 'eager'
  iframe.allowFullscreen = true
  iframe.referrerPolicy = 'strict-origin-when-cross-origin'
  iframe.onload = () => {
    if (loadTimer) clearTimeout(loadTimer)
    loading.value = false
  }
  iframe.onerror = () => {
    if (loadTimer) clearTimeout(loadTimer)
    loading.value = false
    failed.value = true
  }
  host.value.append(iframe)

  loadTimer = setTimeout(() => {
    loading.value = false
  }, 8000)
}

onMounted(renderWidget)
watch(() => props.ticker, renderWidget)
onBeforeUnmount(() => {
  if (loadTimer) clearTimeout(loadTimer)
})
</script>

<template>
  <div class="tradingview-frame" :style="{ height: `${height}px`, minHeight: `${height}px` }">
    <div ref="host" class="tradingview-widget-container"></div>
    <div v-if="loading" class="tradingview-status">Loading TradingView chart…</div>
    <div v-if="failed" class="tradingview-status tradingview-error">
      <span>TradingView could not be loaded.</span>
    </div>
  </div>
  <a class="tradingview-full-chart" :href="`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tradingViewSymbol(ticker))}`" target="_blank" rel="noreferrer">
    Open full {{ ticker }} chart on TradingView
  </a>
</template>