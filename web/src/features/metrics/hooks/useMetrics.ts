'use client';

import { normalizeError } from '@/shared/api';
import { useGetMetricsQuery } from '../api/metricsApi';
import type { MetricsPeriod } from '../types';

export const METRICS_POLL_MS = 5000;

/** CPU and memory of an app's replicas, refreshed every 5 s (the nodes report every 5 s) while the page is in focus. */
export function useMetrics(name: string, period: MetricsPeriod) {
    const query = useGetMetricsQuery(
        { name, period },
        {
            pollingInterval: METRICS_POLL_MS,
            skipPollingIfUnfocused: true,
            refetchOnMountOrArgChange: true,
        },
    );

    return {
        metrics: query.data,
        error: query.error ? normalizeError(query.error) : undefined,
        isLoading: query.isLoading,
        // Switching the period keeps showing the previous data until the new one arrives.
        isFetching: query.isFetching,
        refetch: query.refetch,
    };
}
