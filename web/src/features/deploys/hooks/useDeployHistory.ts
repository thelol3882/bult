'use client';

import { useMemo } from 'react';
import { normalizeError } from '@/shared/api';
import { useGetDeployHistoryInfiniteQuery } from '../api/deploysApi';

/** Deploy history of an app, newest first; `loadMore` appends the next cursor page. */
export function useDeployHistory(name: string) {
    const query = useGetDeployHistoryInfiniteQuery(name);

    const deploys = useMemo(() => query.data?.pages.flatMap((p) => p.results) ?? [], [query.data]);

    return {
        deploys,
        error: query.error ? normalizeError(query.error) : undefined,
        isLoading: query.isLoading,
        hasMore: query.hasNextPage,
        isLoadingMore: query.isFetchingNextPage,
        loadMore: () => void query.fetchNextPage(),
        refetch: () => void query.refetch(),
    };
}
