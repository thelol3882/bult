export const METRICS_PERIODS = ['15m', '1h', '24h'] as const;
export type MetricsPeriod = (typeof METRICS_PERIODS)[number];

/** [ISO timestamp of the bucket start, CPU as % of the replica's limit, memory in bytes]. */
export type MetricsPoint = [string, number, number];

export interface MetricsSeries {
    replica_id: string;
    index: number;
    node: string;
    points: MetricsPoint[];
    /** False once the replica was removed; its history is still returned. */
    live: boolean;
}

export interface MetricsSummary {
    /** Cores in use by all live replicas now. */
    cpu_cores: number;
    mem_bytes: number;
    mem_limit_bytes: number;
    ready_replicas: number;
    desired_replicas: number;
}

export interface AppMetrics {
    period: MetricsPeriod;
    bucket_seconds: number;
    series: MetricsSeries[];
    summary: MetricsSummary;
}
