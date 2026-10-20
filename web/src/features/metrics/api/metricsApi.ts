import { baseApi } from '@/shared/api';
import type { AppMetrics, MetricsPeriod } from '../types';

export const metricsApi = baseApi.injectEndpoints({
    endpoints: (build) => ({
        getMetrics: build.query<AppMetrics, { name: string; period: MetricsPeriod }>({
            query: ({ name, period }) =>
                `/apps/${encodeURIComponent(name)}/metrics?period=${period}`,
        }),
    }),
});

export const { useGetMetricsQuery } = metricsApi;
