'use client';

import { normalizeError } from '@/shared/api';
import { useGetNodesQuery } from '../api/nodesApi';

export const NODES_POLL_MS = 5000;

/** The platform's nodes, refreshed every 5 s (the agents report every 5 s) while the page is in focus. */
export function useNodes() {
    const query = useGetNodesQuery(undefined, {
        pollingInterval: NODES_POLL_MS,
        skipPollingIfUnfocused: true,
    });

    return {
        nodes: query.data,
        error: query.error ? normalizeError(query.error) : undefined,
        isLoading: query.isLoading,
        refetch: query.refetch,
    };
}
