import { useEffect, useMemo, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { agentService } from '@/shared/services/agentService'
import { AirportPoint, FlightPathEdge, FlightPathNode, HeatCell, TrendPoint } from '@/shared/types/api'
import ReactFlow, { Background, BackgroundVariant, Controls, Edge, Node } from 'reactflow'
import { Loader2, Radar, PlaneTakeoff, ShieldAlert, Wind } from 'lucide-react'
import 'reactflow/dist/style.css'

const ICAO_DEFAULT = 'VHHH,EGLL,KJFK'

const FLIGHT_CATEGORY_LABELS = ['VFR', 'MVFR', 'IFR', 'LIFR']

function flightCategoryClass(cat?: string) {
  const normalized = (cat ?? '').toUpperCase()
  if (normalized === 'LIFR') return 'pilot-status pilot-status-lifr'
  if (normalized === 'IFR') return 'pilot-status pilot-status-ifr'
  if (normalized === 'MVFR') return 'pilot-status pilot-status-mvfr'
  return 'pilot-status pilot-status-vfr'
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
          border: '1px solid rgba(137, 154, 255, 0.42)',
          background: 'linear-gradient(145deg, rgba(255,255,255,0.82), rgba(255,255,255,0.56))',
          backdropFilter: 'blur(8px)',
          boxShadow: '0 8px 20px rgba(118, 133, 205, 0.16)',
          color: '#2d355f',
          padding: '6px 8px',
        },
      }))
      const edges: Edge[] = rawEdges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        animated: true,
        style: { stroke: '#6f86ff', strokeWidth: 1.65 },
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
    <div className="flex flex-col gap-4 fade-in-up">
      <Card className="overflow-hidden">
        <div className="h-1.5 w-full bg-gradient-to-r from-indigo-400 via-violet-400 to-sky-400" />
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Pilot Operations Visual Intelligence</CardTitle>
          <p className="text-sm text-muted-foreground">
            Glassy, real-time decision support across weather, safety, and route dynamics.
          </p>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex gap-2 flex-wrap">
            <Input
              value={icaosInput}
              onChange={(e) => setIcaosInput(e.target.value)}
              placeholder="ICAOs comma-separated (e.g., VHHH,EGLL,KJFK)"
              className="max-w-xl"
            />
            <Button onClick={load} disabled={loading}>
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Updating
                </>
              ) : (
                'Refresh Dashboard'
              )}
            </Button>
          </div>
          {error && <p className="text-sm text-red-500">{error}</p>}

          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
            <Card className="glass-panel-soft">
              <CardContent className="pt-5">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Monitored Airports</p>
                <p className="mt-1 text-2xl font-extrabold tracking-tight">{airports.length}</p>
                <p className="mt-1 text-xs text-muted-foreground">Live ICAO points in current viewport</p>
              </CardContent>
            </Card>
            <Card className="glass-panel-soft">
              <CardContent className="pt-5">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Average Surface Wind</p>
                <p className="mt-1 text-2xl font-extrabold tracking-tight">{averageWind.toFixed(1)} kt</p>
                <p className="mt-1 text-xs text-muted-foreground">Crosswind awareness baseline</p>
              </CardContent>
            </Card>
            <Card className="glass-panel-soft">
              <CardContent className="pt-5">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">High-Risk Airports</p>
                <p className="mt-1 text-2xl font-extrabold tracking-tight">{riskAirports}</p>
                <p className="mt-1 text-xs text-muted-foreground">IFR/LIFR flagged destinations</p>
              </CardContent>
            </Card>
            <Card className="glass-panel-soft">
              <CardContent className="pt-5">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Average Temperature</p>
                <p className="mt-1 text-2xl font-extrabold tracking-tight">{averageTemperature.toFixed(1)}°C</p>
                <p className="mt-1 text-xs text-muted-foreground">Comparative station climate snapshot</p>
              </CardContent>
            </Card>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Radar className="h-4 w-4 text-indigo-500" />
              Airport Map Snapshot
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 text-xs max-h-80 overflow-auto pr-1">
              {airports.map((a) => (
                <div key={a.icao} className="glass-panel-soft rounded-xl px-3 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-semibold text-sm text-slate-700 dark:text-slate-200">{a.icao}</div>
                    <span className={flightCategoryClass(a.flight_cat)}>{(a.flight_cat ?? 'VFR').toUpperCase()}</span>
                  </div>
                  <div className="mt-1 text-[11px] text-muted-foreground">
                    Lat/Lon {a.lat.toFixed(2)} / {a.lon.toFixed(2)}
                  </div>
                  <div className="mt-1.5 grid grid-cols-2 gap-2 text-[11px]">
                    <div className="rounded-lg bg-white/60 px-2 py-1 dark:bg-slate-800/65">Wind: {a.wind_speed_kt ?? '-'} kt</div>
                    <div className="rounded-lg bg-white/60 px-2 py-1 dark:bg-slate-800/65">Temp: {a.temp_c ?? '-'}°C</div>
                  </div>
                </div>
              ))}
              {airports.length === 0 && <p className="text-muted-foreground">No airport points.</p>}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-rose-500" />
              Safety Severity Heatmap
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 text-xs max-h-80 overflow-auto pr-1">
              {heatmap.map((h) => (
                <div key={h.icao} className="glass-panel-soft rounded-xl px-3 py-2.5">
                  <div className="mb-1.5 flex items-center justify-between text-[11px]">
                    <span className="font-semibold text-sm text-slate-700 dark:text-slate-200">{h.icao}</span>
                    <span className="text-muted-foreground">Incidents: {h.incidents}</span>
                  </div>
                  <div className="h-2.5 w-full rounded-full bg-slate-100/80 dark:bg-slate-700/60">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-amber-400 via-orange-500 to-rose-500"
                      style={{ width: `${Math.max(7, (h.severity_score / maxSeverity) * 100)}%` }}
                    />
                  </div>
                  <div className="mt-1 text-[11px] text-muted-foreground">Severity score: {h.severity_score.toFixed(2)}</div>
                </div>
              ))}
              {heatmap.length === 0 && <p className="text-muted-foreground">No heatmap cells.</p>}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Wind className="h-4 w-4 text-sky-500" />
              Weather Trends and Deltas
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2.5 text-xs max-h-80 overflow-auto pr-1">
              {Object.entries(groupedTrend).map(([icao, pts]) => {
                const latest = pts[pts.length - 1]
                const earliest = pts[0]
                const windDelta = (latest?.wind_speed_kt ?? 0) - (earliest?.wind_speed_kt ?? 0)
                const tempDelta = (latest?.temp_c ?? 0) - (earliest?.temp_c ?? 0)
                const windSeries = pts.map((p) => p.wind_speed_kt ?? 0)
                const trendPath = miniLinePath(windSeries)
                return (
                  <div key={icao} className="glass-panel-soft rounded-xl px-3 py-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <b className="text-sm text-slate-700 dark:text-slate-200">{icao}</b>
                      <span className="text-[11px] text-muted-foreground">{pts.length} points</span>
                    </div>
                    <div className="mt-1 text-[11px] text-muted-foreground">Δ Wind: {windDelta.toFixed(1)} kt | Δ Temp: {tempDelta.toFixed(1)}°C</div>
                    <div className="mt-2 rounded-lg bg-white/70 p-1.5 dark:bg-slate-800/70">
                      <svg viewBox="0 0 220 58" className="h-12 w-full">
                        <path d={trendPath} fill="none" stroke="url(#trend-gradient)" strokeWidth="2.5" strokeLinecap="round" />
                        <defs>
                          <linearGradient id="trend-gradient" x1="0" y1="0" x2="1" y2="0">
                            <stop offset="0%" stopColor="#7a87ff" />
                            <stop offset="100%" stopColor="#43b2ff" />
                          </linearGradient>
                        </defs>
                      </svg>
                    </div>
                  </div>
                )
              })}
              {trends.length === 0 && <p className="text-muted-foreground">No trend points.</p>}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <PlaneTakeoff className="h-4 w-4 text-emerald-500" />
              Flight Paths Network
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2.5">
            <div className="grid grid-cols-3 gap-2 text-[11px]">
              <div className="glass-panel-soft rounded-lg p-2">
                <p className="text-muted-foreground">Nodes</p>
                <p className="text-base font-bold">{pathNodeMeta.length}</p>
              </div>
              <div className="glass-panel-soft rounded-lg p-2">
                <p className="text-muted-foreground">Edges</p>
                <p className="text-base font-bold">{pathEdgeMeta.length}</p>
              </div>
              <div className="glass-panel-soft rounded-lg p-2">
                <p className="text-muted-foreground">Suggested Rule</p>
                <p className="text-base font-bold">
                  {riskAirports > 0 ? 'Review alternates' : 'Normal ops'}
                </p>
              </div>
            </div>
            <div className="h-72 overflow-hidden rounded-xl border border-white/55 bg-white/68 shadow-sm backdrop-blur dark:border-slate-700/65 dark:bg-slate-900/60">
              <ReactFlow nodes={pathNodes} edges={pathEdges} fitView>
                <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="rgba(111,134,255,0.28)" />
                <Controls />
              </ReactFlow>
            </div>
            <div className="flex flex-wrap gap-2 pt-0.5">
              {FLIGHT_CATEGORY_LABELS.map((label) => (
                <span
                  key={label}
                  className={flightCategoryClass(label)}
                >
                  {label}
                </span>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

