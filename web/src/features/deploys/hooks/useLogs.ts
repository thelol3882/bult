'use client';

import { normalizeError } from '@/shared/api';
import { useGetLogsQuery } from '../api/deploysApi';

export const LOGS_POLL_MS = 3000;

/** Tail of one replica's output, refreshed every 3 s while the page is in focus. */
export function useLogs(name: string, tail: number, replica?: number) {
    const query = useGetLogsQuery(
        { name, tail, replica },
        {
            pollingInterval: LOGS_POLL_MS,
            skipPollingIfUnfocused: true,
            refetchOnMountOrArgChange: true,
        },
    );

    return {
        logs: query.data,
        error: query.error ? normalizeError(query.error) : undefined,
        isLoading: query.isLoading,
    };
}
