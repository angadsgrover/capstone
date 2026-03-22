import { useEffect, useMemo, useState } from 'react'
import { agentService } from '@/shared/services/agentService'
import { AirportPoint, FlightPathEdge, FlightPathNode, HeatCell, TrendPoint } from '@/shared/types/api'
import ReactFlow, { Background, BackgroundVariant, Controls, Edge, Node } from 'reactflow'
import MaterialIcon from '@/components/ui/MaterialIcon'
import { cn } from '@/lib/utils'
import 'reactflow/dist/style.css'

const ICAO_DEFAULT = 'VHHH,EGLL,KJFK'

const FLIGHT_CATEGORY_LABELS = ['VFR', 'MVFR', 'IFR', 'LIFR']

function flightCategoryClass(cat?: string) {
  const normalized = (cat ?? '').toUpperCase()
  if (normalized === 'LIFR') return 'inline-flex items-center justify-center px-3 py-1 rounded-lg text-xs font-semibold border bg-error/10 text-error border-error/30'
  if (normalized === 'IFR') return 'inline-flex items-center justify-center px-3 py-1 rounded-lg text-xs font-semibold border bg-[hsl(var(--status-ifr)/0.12)] text-[hsl(var(--status-ifr))] border-[hsl(var(--status-ifr)/0.3)]'
  if (normalized === 'MVFR') return 'inline-flex items-center justify-center px-3 py-1 rounded-lg text-xs font-semibold border bg-[hsl(var(--status-mvfr)/0.12)] text-[hsl(var(--status-mvfr))] border-[hsl(var(--status-mvfr)/0.3)]'
  return 'inline-flex items-center justify-center px-3 py-1 rounded-lg text-xs font-semibold border bg-[hsl(var(--status-vfr)/0.12)] text-[hsl(var(--status-vfr))] border-[hsl(var(--status-vfr)/0.3)]'
}

function miniLinePath(values: number[], width = 220, height = 58) {
  if (values.length === 0) return ''
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = Math.max(max - min, 1)

  const points = values.map((val, idx) => {
    const x = (idx / Math.max(values.length - 1, 1)) * width
    const y = height - ((val - min) / range) * (height - 6) - 3
    return `${x},${y}`
  })

  return `M ${points.join(' L ')}`
}

function avg(nums: number[]) {
  if (!nums.length) return 0
  return nums.reduce((sum, n) => sum + n, 0) / nums.length
}

export default function VisualizationsView() {
  const [airports, setAirports] = useState<AirportPoint[]>([])
  const [trends, setTrends] = useState<TrendPoint[]>([])
  const [heatmap, setHeatmap] = useState<HeatCell[]>([])
  const [pathNodes, setPathNodes] = useState<Node[]>([])
  const [pathEdges, setPathEdges] = useState<Edge[]>([])
  const [pathNodeMeta, setPathNodeMeta] = useState<FlightPathNode[]>([])
  const [pathEdgeMeta, setPathEdgeMeta] = useState<FlightPathEdge[]>([])
  const [icaosInput, setIcaosInput] = useState(ICAO_DEFAULT)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const selectedIcaos = useMemo(
    () => icaosInput.split(',').map((x) => x.trim().toUpperCase()).filter(Boolean).slice(0, 6),
    [icaosInput]
  )

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [mapData, trendData, pathData, heatData] = await Promise.all([
        agentService.getAirportMap(16),
        agentService.getWeatherTrends(selectedIcaos.length ? selectedIcaos : ICAO_DEFAULT.split(','), 72),
        agentService.getFlightPaths(8),
        agentService.getSafetyHeatmap(20),
      ])
      setAirports(mapData.airports ?? [])
      setTrends(trendData.points ?? [])
      setHeatmap(heatData.cells ?? [])

      const rawNodes: FlightPathNode[] = pathData.nodes ?? []
      const rawEdges: FlightPathEdge[] = pathData.edges ?? []
      setPathNodeMeta(rawNodes)
      setPathEdgeMeta(rawEdges)

      const nodes: Node[] = rawNodes.map((n, idx) => ({
        id: n.id,
        position: { x: 80 + (idx % 4) * 180, y: 80 + Math.floor(idx / 4) * 120 },
        data: {
          label: `${n.label ?? n.id} ${typeof n.lat === 'number' && typeof n.lon === 'number' ? `(${n.lat.toFixed(2)}, ${n.lon.toFixed(2)})` : ''}`,
        },
        style: {
          fontSize: 11,
          borderRadius: 12,
          border: '1px solid hsl(var(--primary) / 0.35)',
          background: 'linear-gradient(145deg, hsl(var(--surface) / 0.92), hsl(var(--surface-container-low) / 0.88))',
          backdropFilter: 'blur(8px)',
          boxShadow: '0 8px 20px hsl(var(--surface-container-lowest) / 0.3)',
          color: 'hsl(var(--on-surface))',
          padding: '6px 8px',
        },
      }))
      const edges: Edge[] = rawEdges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        animated: true,
        style: { stroke: 'hsl(var(--primary))', strokeWidth: 1.65 },
      }))
      setPathNodes(nodes)
      setPathEdges(edges)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const groupedTrend = useMemo(() => {
    const byIcao: Record<string, TrendPoint[]> = {}
    for (const p of trends) {
      byIcao[p.icao] = byIcao[p.icao] ?? []
      byIcao[p.icao].push(p)
    }
    return byIcao
  }, [trends])

  const averageWind = useMemo(() => {
    const winds = airports
      .map((a) => a.wind_speed_kt)
      .filter((n): n is number => typeof n === 'number')
    return avg(winds)
  }, [airports])

  const averageTemperature = useMemo(() => {
    const temps = airports
      .map((a) => a.temp_c)
      .filter((n): n is number => typeof n === 'number')
    return avg(temps)
  }, [airports])

  const riskAirports = useMemo(() => {
    return airports.filter((a) => {
      const cat = (a.flight_cat ?? '').toUpperCase()
      return cat === 'IFR' || cat === 'LIFR'
    }).length
  }, [airports])

  const maxSeverity = useMemo(() => {
    return Math.max(...heatmap.map((h) => h.severity_score), 1)
  }, [heatmap])

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className={cn(
        "overflow-hidden rounded-2xl border border-outline-variant/20",
        "bg-surface-container-low/80 shadow-xl glass-panel"
      )}>
        <div className="h-1.5 w-full bg-gradient-to-r from-primary via-secondary to-primary-container" />
        <div className="p-6">
          <div className="mb-4">
            <div className="flex items-center gap-3 mb-2">
              <MaterialIcon icon="monitoring" className="text-2xl text-secondary" />
              <h2 className="text-lg font-bold text-primary">Visual Intelligence Dashboard</h2>
            </div>
            <p className="text-sm text-on-surface-variant">
              Real-time decision support across weather, safety, and route dynamics.
            </p>
          </div>
          <div className="flex gap-3 flex-wrap">
            <input
              type="text"
              value={icaosInput}
              onChange={(e) => setIcaosInput(e.target.value)}
              placeholder="ICAOs comma-separated (e.g., VHHH,EGLL,KJFK)"
              className={cn(
                "flex-1 px-4 py-3 rounded-xl bg-surface-container-highest/60 backdrop-blur-xl",
                "border border-outline-variant/20 text-on-surface placeholder:text-on-surface-variant/40",
                "focus:outline-none focus:border-secondary/50 focus:ring-2 focus:ring-secondary/20",
                "transition-all duration-300 max-w-xl"
              )}
            />
            <button
              onClick={load}
              disabled={loading}
              className={cn(
                "px-6 py-3 rounded-xl font-semibold text-sm uppercase tracking-wider transition-all duration-300",
                "flex items-center justify-center gap-2",
                !loading
                  ? "user-gradient text-on-primary-container shadow-lg shadow-primary/20 hover:shadow-primary/30 hover:scale-105 hover:brightness-110 active:scale-95"
                  : "bg-surface-container text-on-surface-variant/30 cursor-not-allowed"
              )}
            >
              {loading ? (
                <>
                  <MaterialIcon icon="sync" className="text-base animate-spin" />
                  <span className="hidden sm:inline">Updating</span>
                </>
              ) : (
                <>
                  <MaterialIcon icon="refresh" className="text-base" filled />
                  <span className="hidden sm:inline">Refresh</span>
                </>
              )}
            </button>
          </div>
          {error && <p className="text-sm text-error mt-3">{error}</p>}

          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mt-6">
            <div className={cn(
              "glass-panel rounded-2xl p-5 border border-outline-variant/10",
              "bg-surface-container-high/50 hover:bg-surface-container-highest/60 hover:scale-105 transition-all duration-300"
            )}>
              <div className="flex items-center gap-2 mb-2">
                <MaterialIcon icon="location_on" className="text-secondary" />
                <p className="text-xs uppercase tracking-wide text-on-surface-variant font-semibold">Monitored Airports</p>
              </div>
              <p className="mt-1 text-2xl font-extrabold tracking-tight text-primary">{airports.length}</p>
              <p className="mt-1 text-xs text-on-surface-variant">Live ICAO points in current viewport</p>
            </div>
            <div className={cn(
              "glass-panel rounded-2xl p-5 border border-outline-variant/10",
              "bg-surface-container-high/50 hover:bg-surface-container-highest/60 hover:scale-105 transition-all duration-300"
            )}>
              <div className="flex items-center gap-2 mb-2">
                <MaterialIcon icon="air" className="text-secondary" />
                <p className="text-xs uppercase tracking-wide text-on-surface-variant font-semibold">Average Surface Wind</p>
              </div>
              <p className="mt-1 text-2xl font-extrabold tracking-tight text-primary">{averageWind.toFixed(1)} kt</p>
              <p className="mt-1 text-xs text-on-surface-variant">Crosswind awareness baseline</p>
            </div>
            <div className={cn(
              "glass-panel rounded-2xl p-5 border border-outline-variant/10",
              "bg-surface-container-high/50 hover:bg-surface-container-highest/60 hover:scale-105 transition-all duration-300"
            )}>
              <div className="flex items-center gap-2 mb-2">
                <MaterialIcon icon="warning" className="text-[hsl(var(--status-ifr))]" />
                <p className="text-xs uppercase tracking-wide text-on-surface-variant font-semibold">High-Risk Airports</p>
              </div>
              <p className="mt-1 text-2xl font-extrabold tracking-tight text-primary">{riskAirports}</p>
              <p className="mt-1 text-xs text-on-surface-variant">IFR/LIFR flagged destinations</p>
            </div>
            <div className={cn(
              "glass-panel rounded-2xl p-5 border border-outline-variant/10",
              "bg-surface-container-high/50 hover:bg-surface-container-highest/60 hover:scale-105 transition-all duration-300"
            )}>
              <div className="flex items-center gap-2 mb-2">
                <MaterialIcon icon="thermostat" className="text-secondary" />
                <p className="text-xs uppercase tracking-wide text-on-surface-variant font-semibold">Average Temperature</p>
              </div>
              <p className="mt-1 text-2xl font-extrabold tracking-tight text-primary">{averageTemperature.toFixed(1)}°C</p>
              <p className="mt-1 text-xs text-on-surface-variant">Comparative station climate snapshot</p>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className={cn(
          "rounded-2xl border border-outline-variant/20 overflow-hidden",
          "bg-surface-container-low shadow-xl"
        )}>
          <div className="px-5 py-4 border-b border-outline-variant/10 bg-surface-container-high/30">
            <div className="flex items-center gap-2">
              <MaterialIcon icon="radar" className="text-base text-secondary" />
              <h3 className="text-sm font-bold text-primary">Airport Map Snapshot</h3>
            </div>
          </div>
          <div className="p-4">
            <div className="space-y-3 text-xs max-h-80 overflow-auto pr-1">
              {airports.map((a) => (
                <div key={a.icao} className={cn(
                  "glass-panel-soft rounded-xl px-4 py-3 border border-outline-variant/10",
                  "hover:bg-surface-container-highest/60 hover:scale-[1.02] hover:border-secondary/20",
                  "transition-all duration-300"
                )}>
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-semibold text-sm text-primary">{a.icao}</div>
                    <span className={flightCategoryClass(a.flight_cat)}>{(a.flight_cat ?? 'VFR').toUpperCase()}</span>
                  </div>
                  <div className="mt-1 text-[11px] text-on-surface-variant">
                    Lat/Lon {a.lat.toFixed(2)} / {a.lon.toFixed(2)}
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                    <div className={cn(
                      "rounded-lg px-2.5 py-1.5 bg-surface-container-highest/80 border border-outline-variant/10"
                    )}>
                      <MaterialIcon icon="air" className="inline-block text-xs mr-1" />
                      Wind: {a.wind_speed_kt ?? '-'} kt
                    </div>
                    <div className={cn(
                      "rounded-lg px-2.5 py-1.5 bg-surface-container-highest/80 border border-outline-variant/10"
                    )}>
                      <MaterialIcon icon="thermostat" className="inline-block text-xs mr-1" />
                      Temp: {a.temp_c ?? '-'}°C
                    </div>
                  </div>
                </div>
              ))}
              {airports.length === 0 && <p className="text-on-surface-variant text-center py-8">No airport points.</p>}
            </div>
          </div>
        </div>

        <div className={cn(
          "rounded-2xl border border-outline-variant/20 overflow-hidden",
          "bg-surface-container-low shadow-xl"
        )}>
          <div className="px-5 py-4 border-b border-outline-variant/10 bg-surface-container-high/30">
            <div className="flex items-center gap-2">
              <MaterialIcon icon="warning_amber" className="text-base text-error" />
              <h3 className="text-sm font-bold text-primary">Safety Severity Heatmap</h3>
            </div>
          </div>
          <div className="p-4">
            <div className="space-y-3 text-xs max-h-80 overflow-auto pr-1">
              {heatmap.map((h) => (
                <div key={h.icao} className={cn(
                  "glass-panel-soft rounded-xl px-4 py-3 border border-outline-variant/10",
                  "hover:bg-surface-container-highest/60 hover:scale-[1.02] hover:border-error/20",
                  "transition-all duration-300"
                )}>
                  <div className="mb-2 flex items-center justify-between text-[11px]">
                    <span className="font-semibold text-sm text-primary">{h.icao}</span>
                    <span className="text-on-surface-variant">Incidents: {h.incidents}</span>
                  </div>
                  <div className="h-2.5 w-full rounded-full bg-surface-container-highest/80 border border-outline-variant/10">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-amber-400 via-orange-500 to-rose-500"
                      style={{ width: `${Math.max(7, (h.severity_score / maxSeverity) * 100)}%` }}
                    />
                  </div>
                  <div className="mt-1.5 text-[11px] text-on-surface-variant">Severity score: {h.severity_score.toFixed(2)}</div>
                </div>
              ))}
              {heatmap.length === 0 && <p className="text-on-surface-variant text-center py-8">No heatmap cells.</p>}
            </div>
          </div>
        </div>

        <div className={cn(
          "rounded-2xl border border-outline-variant/20 overflow-hidden",
          "bg-surface-container-low shadow-xl"
        )}>
          <div className="px-5 py-4 border-b border-outline-variant/10 bg-surface-container-high/30">
            <div className="flex items-center gap-2">
              <MaterialIcon icon="trending_up" className="text-base text-secondary" />
              <h3 className="text-sm font-bold text-primary">Weather Trends and Deltas</h3>
            </div>
          </div>
          <div className="p-4">
            <div className="space-y-3 text-xs max-h-80 overflow-auto pr-1">
              {Object.entries(groupedTrend).map(([icao, pts]) => {
                const latest = pts[pts.length - 1]
                const earliest = pts[0]
                const windDelta = (latest?.wind_speed_kt ?? 0) - (earliest?.wind_speed_kt ?? 0)
                const tempDelta = (latest?.temp_c ?? 0) - (earliest?.temp_c ?? 0)
                const windSeries = pts.map((p) => p.wind_speed_kt ?? 0)
                const trendPath = miniLinePath(windSeries)
                return (
                  <div key={icao} className={cn(
                    "glass-panel-soft rounded-xl px-4 py-3 border border-outline-variant/10",
                    "hover:bg-surface-container-highest/60 hover:scale-[1.02] hover:border-secondary/20",
                    "transition-all duration-300"
                  )}>
                    <div className="flex items-center justify-between gap-2">
                      <b className="text-sm text-primary">{icao}</b>
                      <span className="text-[11px] text-on-surface-variant">{pts.length} points</span>
                    </div>
                    <div className="mt-1 text-[11px] text-on-surface-variant">Δ Wind: {windDelta.toFixed(1)} kt | Δ Temp: {tempDelta.toFixed(1)}°C</div>
                    <div className="mt-2 rounded-lg bg-surface-container-highest/70 p-2 border border-outline-variant/10">
                      <svg viewBox="0 0 220 58" className="h-12 w-full">
                        <path d={trendPath} fill="none" stroke="url(#trend-gradient)" strokeWidth="2.5" strokeLinecap="round" />
                        <defs>
                          <linearGradient id="trend-gradient" x1="0" y1="0" x2="1" y2="0">
                            <stop offset="0%" stopColor="hsl(var(--primary))" />
                            <stop offset="100%" stopColor="hsl(var(--secondary))" />
                          </linearGradient>
                        </defs>
                      </svg>
                    </div>
                  </div>
                )
              })}
              {trends.length === 0 && <p className="text-on-surface-variant text-center py-8">No trend points.</p>}
            </div>
          </div>
        </div>

        <div className={cn(
          "rounded-2xl border border-outline-variant/20 overflow-hidden",
          "bg-surface-container-low shadow-xl"
        )}>
          <div className="px-5 py-4 border-b border-outline-variant/10 bg-surface-container-high/30">
            <div className="flex items-center gap-2">
              <MaterialIcon icon="flight_takeoff" className="text-base text-[hsl(var(--status-vfr))]" />
              <h3 className="text-sm font-bold text-primary">Flight Paths Network</h3>
            </div>
          </div>
          <div className="p-4 space-y-3">
            <div className="grid grid-cols-3 gap-3 text-[11px]">
              <div className={cn(
                "glass-panel-soft rounded-xl p-3 border border-outline-variant/10",
                "hover:bg-surface-container-highest/60 hover:scale-105 transition-all duration-300"
              )}>
                <p className="text-on-surface-variant mb-1">Nodes</p>
                <p className="text-base font-bold text-primary">{pathNodeMeta.length}</p>
              </div>
              <div className={cn(
                "glass-panel-soft rounded-xl p-3 border border-outline-variant/10",
                "hover:bg-surface-container-highest/60 hover:scale-105 transition-all duration-300"
              )}>
                <p className="text-on-surface-variant mb-1">Edges</p>
                <p className="text-base font-bold text-primary">{pathEdgeMeta.length}</p>
              </div>
              <div className={cn(
                "glass-panel-soft rounded-xl p-3 border border-outline-variant/10",
                "hover:bg-surface-container-highest/60 hover:scale-105 transition-all duration-300"
              )}>
                <p className="text-on-surface-variant mb-1">Rule</p>
                <p className="text-base font-bold text-primary">
                  {riskAirports > 0 ? 'Review' : 'Normal'}
                </p>
              </div>
            </div>
            <div className={cn(
              "h-72 overflow-hidden rounded-xl border border-outline-variant/20",
              "bg-surface-container-highest/60 shadow-inner backdrop-blur"
            )}>
              <ReactFlow nodes={pathNodes} edges={pathEdges} fitView>
                <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="hsl(var(--secondary) / 0.18)" />
                <Controls />
              </ReactFlow>
            </div>
            <div className="flex flex-wrap gap-2 pt-1">
              {FLIGHT_CATEGORY_LABELS.map((label) => (
                <span
                  key={label}
                  className={flightCategoryClass(label)}
                >
                  {label}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

