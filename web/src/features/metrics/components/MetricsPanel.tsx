'use client';

import { useMemo, useState } from 'react';
import { Alert, Button, Card, Loader, SegmentedControl } from '@mantine/core';
import { IconAlertCircle, IconRefresh } from '@tabler/icons-react';
import { EmptyState } from '@/shared/components';
import { useMetrics } from '../hooks/useMetrics';
import { buildChart, formatBytes, formatCores, formatPercent } from '../services/chart';
import { METRICS_PERIODS, type MetricsPeriod } from '../types';
import { MetricChart } from './MetricChart';
import classes from './MetricsPanel.module.css';

const PERIOD_LABELS: Record<MetricsPeriod, string> = {
    '15m': '15 min',
    '1h': '1 hour',
    '24h': '24 hours',
};

/** CPU and memory of the app's replicas; mounted only while its tab is visible, so polling stops with it. */
export function MetricsPanel({ name }: { name: string }) {
    const [period, setPeriod] = useState<MetricsPeriod>('15m');
    const { metrics, error, isLoading, isFetching, refetch } = useMetrics(name, period);

    const cpu = useMemo(() => (metrics ? buildChart(metrics, 'cpu') : null), [metrics]);
    const mem = useMemo(() => (metrics ? buildChart(metrics, 'mem') : null), [metrics]);

    return (
        <div className={classes.root}>
            <div className={classes.bar}>
                <span className={classes.muted}>Updates every 5 s</span>
                {isFetching && !isLoading && <Loader size={14} />}
                <span className={classes.spacer} />
                <SegmentedControl
                    size="xs"
                    value={period}
                    onChange={(value) => setPeriod(value as MetricsPeriod)}
                    data={METRICS_PERIODS.map((p) => ({ value: p, label: PERIOD_LABELS[p] }))}
                />
            </div>

            {isLoading && (
                <div className={classes.state}>
                    <Loader size="sm" />
                </div>
            )}

            {error && !metrics && (
                <Alert
                    color="red"
                    icon={<IconAlertCircle size={16} />}
                    title="Could not load metrics"
                >
                    {error.message}{' '}
                    <Button
                        variant="subtle"
                        size="compact-sm"
                        leftSection={<IconRefresh size={14} />}
                        onClick={() => refetch()}
                    >
                        Try again
                    </Button>
                </Alert>
            )}

            {metrics && (
                <>
                    <div className={classes.tiles}>
                        <Tile
                            label="CPU"
                            value={`${formatCores(metrics.summary.cpu_cores)} cores`}
                        />
                        <Tile
                            label="Memory"
                            value={formatBytes(metrics.summary.mem_bytes)}
                            note={
                                metrics.summary.mem_limit_bytes > 0
                                    ? `of ${formatBytes(metrics.summary.mem_limit_bytes)}`
                                    : undefined
                            }
                        />
                        <Tile
                            label="Replicas"
                            value={`${metrics.summary.ready_replicas}/${metrics.summary.desired_replicas}`}
                            note="ready / desired"
                        />
                    </div>

                    {cpu && mem && cpu.lines.length > 0 ? (
                        <>
                            <MetricChart
                                title="CPU, % of the replica's limit"
                                model={cpu}
                                format={formatPercent}
                                guide={{ value: 100, label: 'limit' }}
                            />
                            <MetricChart title="Memory" model={mem} format={formatBytes} />
                        </>
                    ) : (
                        <EmptyState
                            title="No data yet"
                            description="Readings arrive a few seconds after a replica starts running; a stopped app has none to show."
                        />
                    )}
                </>
            )}
        </div>
    );
}

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
    return (
        <Card padding="md">
            <div className={classes.tileLabel}>{label}</div>
            <div className={classes.tileValue}>
                {value}
                {note && <span className={classes.tileNote}>{note}</span>}
            </div>
        </Card>
    );
}
