<script setup lang="ts">
// The dashboard reads persisted screening and analysis records from the Go API,
// then presents run progress, ticker filters, and per-ticker analysis details.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  ChevronDown,
  CircleHelp,
  Download,
  LoaderCircle,
  List,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
  Search,
  SlidersHorizontal,
  TableProperties,
  X,
} from 'lucide-vue-next'
import TradingViewChart from './components/TradingViewChart.vue'

/** JSON contract for a saved or live screener ticker result. */
type ScreenerResult = {
  ticker: string
  run_id?: string
  as_of: string
  open: number | null
  high: number | null
  low: number | null
  close: number
  change_percent: number | null
  volume: number | null
  indicators: Record<string, number>
  signals: Record<string, boolean>
  score: number
  stop: number | null
  target: number | null
  rr_ratio: number
}

/** Summary used to select a persisted screener run. */
type ScreenerRun = {
  run_id: string
  started_at: string
  universe: string
  selected_symbols: string
  result_count: number
}

/** Advisory entry and risk levels returned by the Go API. */
type TradePlan = {
  setup: string
  actionable: boolean
  entry_rule: string
  entry: number | null
  entry_support?: string
  stop: number | null
  target: number | null
  risk_per_share: number | null
  rr_ratio: number
  data_note?: string
}

/** Manual-review strategy status and levels for a single timeframe. */
type StrategyPlan = {
  strategy: string
  timeframe: string
  as_of: string | null
  status: string
  entry_trigger: boolean
  exit_trigger: boolean
  entry_rule: string
  entry: number | null
  reference_close: number | null
  stop_rule: string
  stop: number | null
  risk_pct: number | null
  risk_cap_pct: number | null
  target: number | null
  target_rule: string
  exit_rule: string
  data_note: string | null
  manual_precondition?: string
  partial_exit_trigger?: boolean
  remaining_exit_trigger?: boolean
}

/** Saved ticker analysis response; optional run IDs support older records. */
type AnalysisResponse = {
  analysis_run_id?: string
  summary: ScreenerResult
  plan: TradePlan
  risk_reward: TradePlan
  strategy_plans?: Record<string, StrategyPlan>
}

/** Analysis lifecycle information polled while a saved run is being processed. */
type AnalysisRunProgress = {
  analysis_run_id: string
  screener_run_id: string | null
  started_at: string
  finished_at: string | null
  status: 'running' | 'completed' | 'failed'
  result_count: number
  expected_count: number
}

/** Per-ticker result fields used to refresh the saved-run list. */
type AnalysisListResult = {
  ticker: string
  actionable: boolean
  strategy_plans?: Record<string, { status?: string }>
}

/** Cached per-ticker status used by local filters and badges. */
type AnalysisStatus = {
  actionable: boolean
  strategy_plans: Record<string, { status?: string }>
}

const symbolsInput = ref('')
const minScore = ref<number | string>('')
const maxScore = ref<number | string>('')
const scoreSortOrder = ref<'desc' | 'asc'>('desc')
const selectedSetup = ref('all')
const selectedSetupStatus = ref('entry_or_watch')
const strategySetupOptions = [
  ['MAMA_daily', 'MAMA · Daily'],
  ['MAMA_4h', 'MAMA · 4-hour'],
  ['PAPA_daily', 'PAPA · Daily'],
  ['TITA_daily', 'TITA · Daily'],
  ['CALMA_weekly', 'CALMA · Weekly'],
  ['FISHBALL_30m', 'FISHBALL · 30-minute'],
  ['BOPIS_daily', 'BOPIS · Daily'],
  ['BUNSO_15m', 'BUNSO · 15-minute'],
  ['BUNSO_1h', 'BUNSO · 1-hour'],
  ['LOLO_weekly', 'LOLO · Weekly'],
  ['TITO_daily', 'TITO · Daily'],
  ['KASAMBAHAY_daily', 'KASAMBAHAY · Daily'],
  ['SUPERTREND_daily', 'SUPERTREND · Daily'],
  ['SUPERTREND_5m', 'SUPERTREND · 5-minute'],
  ['SUPERTREND_15m', 'SUPERTREND · 15-minute'],
  ['ALLIGATOR_daily', 'ALLIGATOR · Daily'],
  ['BREAD_AND_BUTTER_daily', 'BREAD AND BUTTER · Daily'],
  ['BREAD_AND_BUTTER_1h', 'BREAD AND BUTTER · 1-hour'],
] as const
const screenerRuns = ref<ScreenerRun[]>([])
const selectedRunId = ref('')
const storedResults = ref<ScreenerResult[]>([])
const analysisStatuses = ref<Record<string, AnalysisStatus>>({})
const screenerCollapsed = ref(false)
const symbolsOnly = ref(false)
const failures = ref<{ ticker: string; error: string }[]>([])
const selectedTicker = ref('')
const chartHeight = ref(560)
const analysis = ref<AnalysisResponse | null>(null)
const analysisRunProgress = ref<AnalysisRunProgress | null>(null)
const screening = ref(false)
const loadingAnalysis = ref(false)
const errorMessage = ref('')
const requestCount = ref(0)
const installPromptAvailable = ref(false)
const isOnline = ref(navigator.onLine)

/** Browser-specific install event exposed by supported PWA-capable browsers. */
type InstallPromptEvent = Event & {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>
}

let deferredInstallPrompt: InstallPromptEvent | null = null
let analysisPollTimer: number | undefined
let analysisPollGeneration = 0
let missingRunPolls = 0
let analysisRequestGeneration = 0

function captureInstallPrompt(event: Event) {
  event.preventDefault()
  deferredInstallPrompt = event as InstallPromptEvent
  installPromptAvailable.value = true
}

async function installApp() {
  if (!deferredInstallPrompt) return

  try {
    await deferredInstallPrompt.prompt()
    await deferredInstallPrompt.userChoice
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Could not open the app install prompt'
  } finally {
    deferredInstallPrompt = null
    installPromptAvailable.value = false
  }
}

function handleAppInstalled() {
  deferredInstallPrompt = null
  installPromptAvailable.value = false
}

function updateOnlineStatus() {
  isOnline.value = navigator.onLine
}

function updateAnalysisStatus(
  ticker: string,
  actionable: boolean,
  strategyPlans?: Record<string, { status?: string }>,
) {
  analysisStatuses.value = {
    ...analysisStatuses.value,
    [ticker.toUpperCase()]: {
      actionable,
      strategy_plans: strategyPlans ?? {},
    },
  }
}

function matchesSetupStatus(status: string | undefined) {
  const normalizedStatus = status?.toUpperCase()
  if (!normalizedStatus) return false
  if (selectedSetupStatus.value === 'any') return true
  if (selectedSetupStatus.value === 'entry_or_watch') {
    return normalizedStatus === 'ENTRY_TRIGGERED' || normalizedStatus === 'WATCH'
  }
  return normalizedStatus === selectedSetupStatus.value
}

const symbolCount = computed(() => symbolsInput.value.split(',').filter((item) => item.trim()).length)
const scoreRangeInvalid = computed(() => {
  const minimum = minScore.value === '' ? null : Number(minScore.value)
  const maximum = maxScore.value === '' ? null : Number(maxScore.value)
  return minimum != null && maximum != null
    && Number.isFinite(minimum)
    && Number.isFinite(maximum)
    && minimum > maximum
})
const results = computed(() => {
  const requested = new Set(symbolsInput.value.split(',').map((item) => item.trim().toUpperCase()).filter(Boolean))
  const minimum = minScore.value === '' ? null : Number(minScore.value)
  const maximum = maxScore.value === '' ? null : Number(maxScore.value)
  if (scoreRangeInvalid.value) return []

  return storedResults.value.filter((row) => {
    const matchesTicker = requested.size === 0 || requested.has(row.ticker)
    const matchesMinimum = minimum == null || !Number.isFinite(minimum) || row.score >= minimum
    const matchesMaximum = maximum == null || !Number.isFinite(maximum) || row.score <= maximum
    const savedAnalysis = analysisStatuses.value[row.ticker.toUpperCase()]
    const matchesSetup = selectedSetup.value === 'all'
      || (selectedSetup.value === 'actionable' && Boolean(savedAnalysis?.actionable))
      || (selectedSetup.value === 'any_strategy' && Object.values(savedAnalysis?.strategy_plans ?? {}).some((plan) => matchesSetupStatus(plan.status)))
      || (strategySetupOptions.some(([key]) => key === selectedSetup.value)
        && matchesSetupStatus(savedAnalysis?.strategy_plans[selectedSetup.value]?.status))
    return matchesTicker && matchesMinimum && matchesMaximum && matchesSetup
  }).sort((left, right) => {
    const scoreDifference = scoreSortOrder.value === 'desc'
      ? right.score - left.score
      : left.score - right.score
    return scoreDifference || left.ticker.localeCompare(right.ticker)
  })
})
const selectedRow = computed(() => results.value.find((item) => item.ticker === selectedTicker.value) ?? null)
const indicatorRows = computed(() => {
  const values = analysis.value?.summary.indicators ?? {}
  return [
    ['ALMA · 21', 'ALMA'],
    ['EMA · 9', 'EMA9'],
    ['EMA · 50', 'EMA50'],
    ['EMA · 100', 'EMA100'],
    ['EMA · 200', 'EMA200'],
    ['RSI · 14', 'RSI_14'],
    ['MACD histogram', 'MACDh_12_26_9'],
    ['ATR · 14', 'ATRr_14'],
    ['Bollinger mid', 'BBM_20_2.0'],
    ['CCI · 20', 'CCI_20'],
    ['ADX · 14', 'ADX_14'],
    ['TRIX · 7', 'TRIX_7_9'],
    ['Fisher · 9', 'FISHERT_9_1'],
  ].map(([label, key]) => ({ label, value: values[key] }))
})

const activeSignalCount = computed(() => Object.values(selectedRow.value?.signals ?? {}).filter(Boolean).length)

function formatPrice(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '—'
  return new Intl.NumberFormat('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)
}

function formatVolume(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '—'
  return new Intl.NumberFormat('en-GB', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

function formatPercent(value: number | null) {
  if (value == null || !Number.isFinite(value)) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

function changeTone(value: number | null) {
  return value == null ? 'neutral' : value >= 0 ? 'positive' : 'negative'
}

function formatDate(value: string) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(value))
}

/** Use the API's stable error message when available, otherwise its status. */
async function readError(response: Response) {
  try {
    const body = await response.json()
    return body.error ?? `Request failed (${response.status})`
  } catch {
    return `Request failed (${response.status})`
  }
}

async function loadAnalysis(
  ticker: string,
  quietMissing = analysisRunProgress.value?.status === 'running',
) {
  // Ignore stale responses after selection changes; a 404 may be temporary
  // while the matching saved analysis run is still processing.
  selectedTicker.value = ticker
  loadingAnalysis.value = true
  const requestGeneration = ++analysisRequestGeneration
  try {
    const runFilter = selectedRunId.value ? `?screener_run_id=${encodeURIComponent(selectedRunId.value)}` : ''
    const response = await fetch(`/api/analysis/${encodeURIComponent(ticker)}${runFilter}`)
    if (quietMissing && response.status === 404) {
      analysis.value = null
      errorMessage.value = ''
      return
    }
    if (!response.ok) throw new Error(await readError(response))
    const result = await response.json() as AnalysisResponse
    if (requestGeneration === analysisRequestGeneration && selectedTicker.value === ticker) {
      analysis.value = result
      updateAnalysisStatus(
        ticker,
        result.plan.actionable,
        result.strategy_plans,
      )
      errorMessage.value = ''
    }
  } catch (error) {
    if (requestGeneration === analysisRequestGeneration && selectedTicker.value === ticker) {
      errorMessage.value = error instanceof Error ? error.message : 'Could not load analysis'
      analysis.value = null
    }
  } finally {
    if (requestGeneration === analysisRequestGeneration) loadingAnalysis.value = false
  }
}

function stopAnalysisPolling() {
  analysisPollGeneration += 1
  if (analysisPollTimer !== undefined) {
    window.clearTimeout(analysisPollTimer)
    analysisPollTimer = undefined
  }
}

function startAnalysisPolling(screenerRunId: string) {
  // Poll the saved analysis lifecycle instead of re-running analysis in-browser.
  stopAnalysisPolling()
  analysisRunProgress.value = null
  missingRunPolls = 0
  const generation = analysisPollGeneration

  const poll = async () => {
    if (generation !== analysisPollGeneration || selectedRunId.value !== screenerRunId) return

    try {
      const response = await fetch('/api/analysis/runs?limit=50')
      if (!response.ok) throw new Error(await readError(response))
      const payload = await response.json() as { runs: AnalysisRunProgress[] }
      const progress = payload.runs.find((run) => run.screener_run_id === screenerRunId) ?? null
      analysisRunProgress.value = progress

      if (!progress) {
        missingRunPolls += 1
        if (missingRunPolls < 10) {
          analysisPollTimer = window.setTimeout(() => { void poll() }, 2000)
        }
        return
      }

      await refreshAnalysisStatuses(progress.analysis_run_id)
      if (progress.status === 'running') {
        if (selectedTicker.value && analysis.value?.analysis_run_id !== progress.analysis_run_id) {
          await loadAnalysis(selectedTicker.value, true)
        }
        if (generation === analysisPollGeneration) {
          analysisPollTimer = window.setTimeout(() => { void poll() }, 2000)
        }
        return
      }

      if (selectedTicker.value) await loadAnalysis(selectedTicker.value, true)
      stopAnalysisPolling()
    } catch (error) {
      if (generation !== analysisPollGeneration) return
      errorMessage.value = error instanceof Error ? error.message : 'Could not refresh analysis progress'
      analysisPollTimer = window.setTimeout(() => { void poll() }, 5000)
    }
  }

  void poll()
}

watch([minScore, maxScore, symbolsInput, selectedSetup, selectedSetupStatus, analysisStatuses], () => {
  if (results.value.some((row) => row.ticker === selectedTicker.value)) return

  const firstVisible = results.value[0]
  if (firstVisible) {
    void loadAnalysis(firstVisible.ticker)
  } else {
    selectedTicker.value = ''
    analysis.value = null
  }
})

async function runScreen() {
  // Load results from the selected persisted screener run, then follow analysis
  // progress for that run; this does not initiate a market scan.
  if (!selectedRunId.value) {
    errorMessage.value = 'No saved screener run is selected.'
    return
  }

  screening.value = true
  stopAnalysisPolling()
  analysisRunProgress.value = null
  errorMessage.value = ''
  failures.value = []
  requestCount.value += 1
  try {
    const response = await fetch(`/api/screen/results?run_id=${encodeURIComponent(selectedRunId.value)}&limit=1000`)
    if (!response.ok) throw new Error(await readError(response))
    const payload = await response.json()
    storedResults.value = payload.results as ScreenerResult[]
    analysisStatuses.value = {}
    failures.value = []
    if (storedResults.value.length === 0) {
      selectedTicker.value = ''
      analysis.value = null
      if (failures.value.length) errorMessage.value = 'Price history could not be fetched for the submitted tickers.'
      return
    }
    const firstTickerToLoad = results.value[0] ?? (
      selectedSetup.value !== 'all' ? storedResults.value[0] : undefined
    )
    if (firstTickerToLoad) {
      await loadAnalysis(firstTickerToLoad.ticker, true)
      startAnalysisPolling(selectedRunId.value)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Could not run screener'
  } finally {
    screening.value = false
  }
}

/** Refresh per-ticker statuses shown in the screener list. */
async function refreshAnalysisStatuses(analysisRunId: string) {
  const response = await fetch(
    `/api/analysis/results?run_id=${encodeURIComponent(analysisRunId)}&limit=1000`,
  )
  if (!response.ok) throw new Error(await readError(response))
  const payload = await response.json() as { results: AnalysisListResult[] }
  const statuses: Record<string, AnalysisStatus> = {}
  for (const result of payload.results) {
    statuses[result.ticker.toUpperCase()] = {
      actionable: result.actionable,
      strategy_plans: result.strategy_plans ?? {},
    }
  }
  analysisStatuses.value = statuses
}

/** Load recent persisted runs and select the newest when none is selected. */
async function loadSavedRuns() {
  screening.value = true
  errorMessage.value = ''
  try {
    const response = await fetch('/api/screen/runs?limit=50')
    if (!response.ok) throw new Error(await readError(response))
    const payload = await response.json()
    screenerRuns.value = payload.runs as ScreenerRun[]
    if (!screenerRuns.value.length) {
      errorMessage.value = 'No saved screener runs found in PostgreSQL.'
      return
    }
    if (!screenerRuns.value.some((run) => run.run_id === selectedRunId.value)) {
      selectedRunId.value = screenerRuns.value[0].run_id
    }
    await runScreen()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Could not load saved runs'
  } finally {
    screening.value = false
  }
}

onMounted(() => {
  void loadSavedRuns()
  window.addEventListener('beforeinstallprompt', captureInstallPrompt)
  window.addEventListener('appinstalled', handleAppInstalled)
  window.addEventListener('online', updateOnlineStatus)
  window.addEventListener('offline', updateOnlineStatus)
})

onBeforeUnmount(() => {
  stopAnalysisPolling()
  window.removeEventListener('beforeinstallprompt', captureInstallPrompt)
  window.removeEventListener('appinstalled', handleAppInstalled)
  window.removeEventListener('online', updateOnlineStatus)
  window.removeEventListener('offline', updateOnlineStatus)
})
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <a class="brand" href="#top" aria-label="Market Desk home">
        <span class="brand-mark"><Activity :size="18" :stroke-width="2.2" /></span>
        <span>MARKET<span class="brand-light">/</span>DESK</span>
      </a>
      <div class="topbar-center"><span class="live-dot"></span> POSTGRESQL SNAPSHOTS <span class="topbar-divider">/</span> SCREEN + ANALYSIS</div>
      <div class="topbar-actions">
        <button v-if="installPromptAvailable" class="install-button" @click="installApp">
          <Download :size="14" />
          <span>Install app</span>
        </button>
        <button class="icon-button help-button" title="Saved screen data is read from PostgreSQL. Interactive charts are embedded from TradingView." aria-label="About market data">
          <CircleHelp :size="17" />
        </button>
      </div>
    </header>

    <main id="top" class="workspace">
      <section class="page-heading">
        <div>
          <div class="eyebrow"><span>RESEARCH WORKSPACE</span><span class="eyebrow-line"></span><span>01 / SCREEN</span></div>
          <h1>Equity screener</h1>
          <p class="subtitle">Daily technical signals, risk levels, and market structure.</p>
        </div>
        <div class="heading-meta">
          <span class="meta-label">LATEST SESSION</span>
          <strong>{{ selectedRow ? formatDate(selectedRow.as_of) : '—' }}</strong>
        </div>
      </section>

      <div v-if="!isOnline" class="notice warning-notice offline-notice" role="status">
        You’re offline. The app shell may still load, but saved market data and charts need a connection.
      </div>
      <div v-if="analysisRunProgress?.status === 'running'" class="notice analysis-progress-notice" role="status" aria-live="polite">
        Analysis is saving stocks: {{ analysisRunProgress.result_count }} / {{ analysisRunProgress.expected_count }} completed. This view refreshes automatically.
      </div>

      <section class="screen-controls" aria-label="Screen criteria">
        <label class="ticker-field">
          <span class="field-label">FILTER TICKERS · OPTIONAL</span>
          <div class="input-wrap">
            <Search :size="17" />
            <input v-model="symbolsInput" aria-label="Filter saved results by ticker" placeholder="e.g. AAPL, MSFT" @keydown.enter="runScreen" />
            <span class="ticker-count">{{ symbolCount }} / 50</span>
          </div>
        </label>

        <label class="compact-field run-field">
          <span class="field-label">SAVED SCREENER RUN</span>
          <span class="select-wrap">
            <select v-model="selectedRunId" aria-label="Saved screener run" @change="runScreen">
              <option v-for="run in screenerRuns" :key="run.run_id" :value="run.run_id">
                {{ formatDate(run.started_at) }} · {{ run.universe || 'custom' }} · {{ run.result_count }}
              </option>
            </select>
            <ChevronDown :size="14" />
          </span>
        </label>

        <label class="compact-field score-filter-field">
          <span class="field-label">MIN SCORE</span>
          <input v-model="minScore" class="score-filter-input" type="number" step="1" placeholder="Any" aria-label="Minimum signal score" />
        </label>

        <label class="compact-field score-filter-field">
          <span class="field-label">MAX SCORE</span>
          <input v-model="maxScore" class="score-filter-input" type="number" step="1" placeholder="Any" aria-label="Maximum signal score" />
        </label>

        <button class="run-button" :disabled="screening || !screenerRuns.length" @click="loadSavedRuns">
          <LoaderCircle v-if="screening" class="spin" :size="16" />
          <RefreshCw v-else :size="16" />
          <span>{{ screening ? 'Loading' : 'Refresh database' }}</span>
        </button>
      </section>

      <div v-if="errorMessage" class="notice error-notice" role="alert">
        <span>{{ errorMessage }}</span>
        <button class="icon-button" aria-label="Dismiss error" @click="errorMessage = ''"><X :size="16" /></button>
      </div>
      <div v-if="failures.length && !errorMessage" class="notice warning-notice">
        {{ failures.length }} ticker{{ failures.length === 1 ? '' : 's' }} could not be fetched: {{ failures.map((item) => item.ticker).join(', ') }}
      </div>

      <section class="summary-strip" aria-label="Screen summary">
        <div class="summary-item"><span class="summary-label">VISIBLE</span><strong>{{ results.length }}</strong><span class="summary-tail">of {{ storedResults.length }} stocks</span></div>
        <div class="summary-item"><span class="summary-label">BULLISH BIAS</span><strong>{{ results.filter((row) => row.score > 0).length }}</strong><span class="summary-tail">positive score</span></div>
        <div class="summary-item"><span class="summary-label">TOP SCORE</span><strong>{{ results.length ? Math.max(...results.map((row) => row.score)) : '—' }}</strong><span class="summary-tail">weighted signals</span></div>
        <div class="summary-item summary-updated"><span class="summary-label">REQUEST</span><strong>{{ String(requestCount).padStart(2, '0') }}</strong><span class="summary-tail">this session</span></div>
      </section>

      <section class="results-layout" :class="{ 'screener-collapsed': screenerCollapsed }" aria-label="Screen results and stock analysis">
        <div v-if="!screenerCollapsed" class="results-pane">
          <div class="section-heading table-heading">
            <div><SlidersHorizontal :size="16" /><h2>Screen results</h2><span class="result-count" :title="`${results.length} of ${storedResults.length} stocks match the current filters`">{{ results.length }} / {{ storedResults.length }}</span></div>
            <div class="screener-actions">
              <button class="pane-action" :aria-pressed="symbolsOnly" :title="symbolsOnly ? 'Show full results table' : 'Show symbols only'" :aria-label="symbolsOnly ? 'Show full results table' : 'Show symbols only'" @click="symbolsOnly = !symbolsOnly">
                <List v-if="symbolsOnly" :size="15" />
                <TableProperties v-else :size="15" />
              </button>
              <label class="setup-filter-control">
                <span>SETUP</span>
                <span class="select-wrap setup-filter-select">
                  <select v-model="selectedSetup" aria-label="Filter results by setup">
                    <option value="all">All setups</option>
                    <option value="any_strategy">Any strategy</option>
                    <option value="actionable">Pullback plan actionable</option>
                    <optgroup label="Strategy setups">
                      <option v-for="[key, label] in strategySetupOptions" :key="key" :value="key">{{ label }}</option>
                    </optgroup>
                  </select>
                  <ChevronDown :size="13" />
                </span>
              </label>
              <label class="setup-filter-control">
                <span>STATUS</span>
                <span class="select-wrap setup-status-select">
                  <select
                    v-model="selectedSetupStatus"
                    aria-label="Filter results by strategy status"
                    :disabled="selectedSetup === 'all' || selectedSetup === 'actionable'"
                  >
                    <option value="entry_or_watch">Entry / Watch</option>
                    <option value="ENTRY_TRIGGERED">Entry triggered</option>
                    <option value="WATCH">Watch</option>
                    <option value="EXIT_TRIGGERED">Exit triggered</option>
                    <option value="any">Any status</option>
                  </select>
                  <ChevronDown :size="13" />
                </span>
              </label>
              <label class="score-sort-control">
                <span class="sort-caption">SORT SCORE</span>
                <span class="select-wrap score-sort-select">
                  <select v-model="scoreSortOrder" aria-label="Sort results by score">
                    <option value="desc">Highest first</option>
                    <option value="asc">Lowest first</option>
                  </select>
                  <ChevronDown :size="13" />
                </span>
              </label>
              <button class="pane-action" title="Collapse screener" aria-label="Collapse screener" @click="screenerCollapsed = true"><PanelLeftClose :size="15" /></button>
            </div>
          </div>

          <div v-if="screening && !results.length" class="table-state">
            <LoaderCircle class="spin" :size="22" /> Fetching daily bars and calculating signals…
          </div>
          <div v-else-if="!results.length" class="table-state empty-state">
            <span class="empty-icon"><Search :size="19" /></span>
            <strong>{{ storedResults.length ? 'No stocks match these filters' : 'No results yet' }}</strong>
            <span>{{ storedResults.length ? (scoreRangeInvalid ? 'Minimum score must not exceed maximum score.' : selectedSetup !== 'all' && !Object.keys(analysisStatuses).length ? 'Analysis has not loaded for this run yet. Matching tickers appear as their analysis is saved.' : 'Adjust the score range or clear the ticker and setup filters to see more stocks.') : 'Run a screen to load the latest daily signals.' }}</span>
          </div>

          <div v-else-if="symbolsOnly" class="symbol-only-list" aria-label="Saved stock symbols">
            <button v-for="row in results" :key="row.ticker" class="symbol-only-item" :class="{ selected: selectedTicker === row.ticker }" @click="loadAnalysis(row.ticker)">
              {{ row.ticker }}
            </button>
          </div>

          <div v-else class="table-scroll">
            <table class="results-table">
              <thead>
                <tr>
                  <th>SYMBOL</th>
                  <th class="numeric">CLOSE</th>
                  <th class="numeric">DAY</th>
                  <th class="numeric">RSI 14</th>
                  <th class="numeric"><button class="score-header-button" :aria-label="`Sort score ${scoreSortOrder === 'desc' ? 'lowest first' : 'highest first'}`" @click.stop="scoreSortOrder = scoreSortOrder === 'desc' ? 'asc' : 'desc'">SCORE <ChevronDown :size="12" :class="{ 'sort-ascending': scoreSortOrder === 'asc' }" /></button></th>
                  <th class="numeric">RISK / TARGET</th>
                  <th aria-label="Open analysis"></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in results" :key="row.ticker" :class="{ selected: selectedTicker === row.ticker }" @click="loadAnalysis(row.ticker)">
                  <td class="symbol-cell"><strong>{{ row.ticker }}</strong><span>{{ formatDate(row.as_of) }}</span></td>
                  <td class="numeric price-cell">{{ formatPrice(row.close) }}</td>
                  <td class="numeric" :class="changeTone(row.change_percent)">
                    <span class="change-value" :class="changeTone(row.change_percent)"><ArrowUpRight v-if="row.change_percent != null && row.change_percent >= 0" :size="13" /><ArrowDownRight v-else-if="row.change_percent != null" :size="13" />{{ formatPercent(row.change_percent) }}</span>
                  </td>
                  <td class="numeric rsi-cell"><span>{{ formatPrice(row.indicators.RSI_14) }}</span><i><b :style="{ width: `${Math.max(0, Math.min(100, row.indicators.RSI_14 ?? 0))}%` }"></b></i></td>
                  <td class="numeric"><span class="score-pill" :class="row.score > 0 ? 'score-positive' : row.score < 0 ? 'score-negative' : 'score-neutral'">{{ row.score > 0 ? '+' : '' }}{{ row.score }}</span></td>
                  <td class="numeric levels-cell"><strong>{{ formatPrice(row.stop) }}</strong><span>{{ formatPrice(row.target) }}</span></td>
                  <td class="open-cell"><ArrowUpRight :size="15" /></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-if="!symbolsOnly" class="table-footnote"><span>INDICATOR SCORE IS A RULE-BASED SIGNAL COUNT</span><span>{{ screening ? 'UPDATING' : 'DAILY · 1D' }}</span></div>
        </div>

        <aside class="analysis-pane" aria-label="Selected stock analysis">
          <div class="section-heading analysis-heading">
            <div>
              <button v-if="screenerCollapsed" class="pane-action reopen-screener" title="Show screener" aria-label="Show screener" @click="screenerCollapsed = false"><PanelLeftOpen :size="15" /></button>
              <Activity :size="16" /><h2>Stock analysis</h2>
            </div>
            <span class="analysis-symbol">{{ selectedTicker || '—' }}</span>
          </div>

          <div v-if="selectedTicker" class="chart-wrap">
            <div class="chart-caption">
              <span>INTERACTIVE DAILY CHART</span>
              <label class="chart-size-control">
                <span>HEIGHT</span>
                <input v-model.number="chartHeight" type="range" min="320" max="1000" step="20" :aria-valuetext="`${chartHeight} pixels`" aria-label="TradingView chart height" />
                <output>{{ chartHeight }}px</output>
              </label>
            </div>
            <TradingViewChart :ticker="selectedTicker" :height="chartHeight" />
          </div>

          <div v-if="loadingAnalysis" class="analysis-state"><LoaderCircle class="spin" :size="22" /><span>Loading analysis…</span></div>
          <div v-else-if="!analysis" class="analysis-state muted-state"><Search :size="19" /><span>The chart is available; no saved analysis snapshot was found for this ticker.</span></div>
          <template v-else>
            <div class="detail-quote">
              <div><span class="field-label">LAST CLOSE · {{ formatDate(analysis.summary.as_of) }}</span><strong>{{ formatPrice(analysis.summary.close) }}</strong></div>
              <span class="detail-change" :class="changeTone(analysis.summary.change_percent)">{{ formatPercent(analysis.summary.change_percent) }}</span>
            </div>

            <div class="detail-stats">
              <div><span>OPEN</span><strong>{{ formatPrice(analysis.summary.open) }}</strong></div>
              <div><span>DAY RANGE</span><strong>{{ formatPrice(analysis.summary.low) }} — {{ formatPrice(analysis.summary.high) }}</strong></div>
              <div><span>VOLUME</span><strong>{{ formatVolume(analysis.summary.volume) }}</strong></div>
              <div><span>ACTIVE SIGNALS</span><strong>{{ activeSignalCount }} / {{ Object.keys(analysis.summary.signals).length }}</strong></div>
            </div>

            <div class="detail-section">
              <div class="detail-section-heading"><h3>Technical readings</h3><span>DAILY</span></div>
              <div class="indicator-grid">
                <div v-for="item in indicatorRows" :key="item.label" class="indicator-row">
                  <span>{{ item.label }}</span><strong>{{ formatPrice(item.value) }}</strong>
                </div>
              </div>
            </div>

            <div class="plan-section">
              <div class="detail-section-heading"><h3>Pullback plan</h3><span v-if="analysis.plan.actionable" class="plan-ready">ACTIONABLE</span><span v-else class="plan-idle">NO SETUP</span></div>
              <p class="plan-rule">{{ analysis.plan.entry_rule }}</p>
              <p v-if="analysis.plan.data_note" class="strategy-unavailable" role="status">{{ analysis.plan.data_note }}</p>
              <div class="plan-levels">
                <div><span>ENTRY<span v-if="analysis.plan.entry_support"> · {{ analysis.plan.entry_support }}</span></span><strong>{{ formatPrice(analysis.plan.entry) }}</strong></div>
                <div><span>STOP</span><strong>{{ formatPrice(analysis.plan.stop) }}</strong></div>
                <div><span>TARGET · {{ analysis.plan.rr_ratio }}R</span><strong>{{ formatPrice(analysis.plan.target) }}</strong></div>
              </div>
            </div>

            <section v-if="analysis.strategy_plans && Object.keys(analysis.strategy_plans).length" class="strategy-section">
              <div class="detail-section-heading"><h3>Strategy suggestions</h3><span>MANUAL REVIEW ONLY</span></div>
              <p class="strategy-disclaimer">Conditional technical setups, not orders or investment advice. Confirm the latest candle before acting.</p>
              <article v-for="(setup, name) in analysis.strategy_plans" :key="name" class="strategy-card">
                <div class="strategy-card-heading">
                  <strong>{{ name }}</strong>
                  <span class="strategy-status" :class="`status-${setup.status.toLowerCase()}`">{{ setup.status.replaceAll('_', ' ') }}</span>
                </div>
                <div class="strategy-meta">{{ setup.timeframe }} · AS OF {{ setup.as_of ? formatDate(setup.as_of) : '—' }}</div>
                <p class="plan-rule">{{ setup.entry_rule }}</p>
                <div class="plan-levels">
                  <div><span>ENTRY</span><strong>{{ formatPrice(setup.entry) }}</strong></div>
                  <div><span>STOP · {{ setup.stop_rule }}</span><strong>{{ formatPrice(setup.stop) }}</strong></div>
                  <div><span>TARGET</span><strong>{{ formatPrice(setup.target) }}</strong></div>
                </div>
                <p class="strategy-exit">{{ setup.risk_pct == null ? 'Risk: —' : `Risk to stop: ${setup.risk_pct.toFixed(2)}%` }} · {{ setup.target_rule }}</p>
                <p class="strategy-exit"><strong>Exit:</strong> {{ setup.exit_rule }}</p>
                <p v-if="setup.partial_exit_trigger || setup.remaining_exit_trigger" class="strategy-exit"><strong>Triggered exits:</strong> <span v-if="setup.partial_exit_trigger">50% partial exit </span><span v-if="setup.remaining_exit_trigger">remaining-position exit</span></p>
                <p v-if="setup.manual_precondition" class="strategy-precondition"><strong>Confirm manually:</strong> {{ setup.manual_precondition }}</p>
                <p v-if="setup.data_note" class="strategy-unavailable">{{ setup.data_note }}</p>
              </article>
            </section>
          </template>
        </aside>
      </section>
    </main>

    <footer class="app-footer"><span>MARKET/DESK <span class="footer-version">GO + VUE</span></span><span>CHARTS BY TRADINGVIEW <span class="footer-divider">·</span> NOT INVESTMENT ADVICE</span></footer>
  </div>
</template>