import type { AppMetrics, MetricsPeriod, MetricsSeries } from '../types';

/**
 * Categorical slots 1-5 of the data-viz palette (blue, orange, aqua, yellow, magenta), picked by
 * replica index so a replica keeps its colour across redeploys. An app has at most 5 replicas.
 */
export const SERIES_COLORS = [
    'var(--series-1)',
    'var(--series-2)',
    'var(--series-3)',
    'var(--series-4)',
    'var(--series-5)',
] as const;

export type Field = 'cpu' | 'mem';

export interface ChartLine {
    /** Key in the data rows. */
    name: string;
    label: string;
    color: string;
    /** Older deploys' replicas and removed replicas are drawn dashed. */
    dashed: boolean;
    /** The replica is running now; a removed one is also muted and sorted last. */
    live: boolean;
    /** The newest value, for the legend. */
    last: number | null;
}

export interface ChartRow {
    time: string;
    [replicaId: string]: string | number | null;
}

export interface ChartModel {
    rows: ChartRow[];
    lines: ChartLine[];
}

const FIELD_AT = { cpu: 1, mem: 2 } as const;

function lastTs(series: MetricsSeries): number {
    const last = series.points[series.points.length - 1];
    return last ? Date.parse(last[0]) : 0;
}

export const REMOVED_SUFFIX = ' · removed';

/** "r0 · bult-node-1"; an older deploy's replica of the same index gets its deploy id as well. */
export function replicaLabel(series: MetricsSeries, older: boolean): string {
    const base = `r${series.index} · ${series.node}`;
    const label = older ? `${base} · ${series.replica_id.slice(0, 6)}` : base;
    return series.live ? label : `${label}${REMOVED_SUFFIX}`;
}

/** A removed replica's colour, faded; the line stays visible but reads as history. */
export function mutedColor(color: string): string {
    return `color-mix(in srgb, ${color} 45%, transparent)`;
}

/** Ids of the series that are not the newest one of their replica index. */
export function olderReplicaIds(series: MetricsSeries[]): Set<string> {
    const newest = new Map<number, MetricsSeries>();
    for (const s of series) {
        const current = newest.get(s.index);
        if (!current || lastTs(s) > lastTs(current)) newest.set(s.index, s);
    }
    return new Set(series.filter((s) => newest.get(s.index) !== s).map((s) => s.replica_id));
}

export function seriesColor(index: number): string {
    return SERIES_COLORS[index % SERIES_COLORS.length];
}

function timeLabel(ms: number, period: MetricsPeriod): string {
    const d = new Date(ms);
    const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    if (period === '15m') return `${hm}:${String(d.getSeconds()).padStart(2, '0')}`;
    return hm;
}

/**
 * Rows on a regular time grid (one per bucket), so a gap in a replica's data shows as a gap and
 * not as two neighbours: a missing bucket is null.
 */
export function buildChart(metrics: AppMetrics, field: Field): ChartModel {
    const { series, bucket_seconds: width, period } = metrics;
    const step = width * 1000;
    const at = FIELD_AT[field];
    const older = olderReplicaIds(series);

    const times = series.flatMap((s) => s.points.map((p) => Date.parse(p[0])));
    if (times.length === 0) return { rows: [], lines: [] };
    const first = Math.min(...times);
    const last = Math.max(...times);

    const values = new Map<string, Map<number, number>>();
    for (const s of series) {
        values.set(s.replica_id, new Map(s.points.map((p) => [Date.parse(p[0]), p[at]])));
    }

    const rows: ChartRow[] = [];
    for (let t = first; t <= last; t += step) {
        const row: ChartRow = { time: timeLabel(t, period) };
        for (const s of series) row[s.replica_id] = values.get(s.replica_id)?.get(t) ?? null;
        rows.push(row);
    }

    const lines: ChartLine[] = series.map((s) => {
        const lastPoint = s.points[s.points.length - 1];
        const color = seriesColor(s.index);
        return {
            name: s.replica_id,
            label: replicaLabel(s, older.has(s.replica_id)),
            color: s.live ? color : mutedColor(color),
            dashed: older.has(s.replica_id) || !s.live,
            live: s.live,
            last: lastPoint ? lastPoint[at] : null,
        };
    });
    // Stable sort: live lines first, the rest keeps its replica order.
    lines.sort((a, b) => Number(b.live) - Number(a.live));
    return { rows, lines };
}

const KIB = 1024;
const MIB = KIB ** 2;
const GIB = KIB ** 3;

export function formatBytes(bytes: number): string {
    if (bytes >= GIB) return `${(bytes / GIB).toFixed(2)} GiB`;
    if (bytes >= MIB) return `${(bytes / MIB).toFixed(bytes >= 100 * MIB ? 0 : 1)} MiB`;
    if (bytes >= KIB) return `${(bytes / KIB).toFixed(0)} KiB`;
    return `${bytes} B`;
}

export function formatPercent(value: number): string {
    return `${value.toFixed(value >= 100 ? 0 : 1)}%`;
}

export function formatCores(cores: number): string {
    return cores >= 1 ? cores.toFixed(2) : cores.toFixed(3);
}
