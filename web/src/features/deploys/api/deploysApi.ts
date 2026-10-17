import { baseApi } from '@/shared/api';
import type { CursorPage } from '@/shared/types';
import type { AppLogs, Deploy, DeployArgs } from '../types';

export const HISTORY_PAGE_SIZE = 20;

export const deployListTag = (name: string) => ({ type: 'Deploy' as const, id: `LIST-${name}` });

export const deploysApi = baseApi.injectEndpoints({
    endpoints: (build) => ({
        startDeploy: build.mutation<Deploy, string>({
            query: (name) => ({
                url: `/apps/${encodeURIComponent(name)}/deploys`,
                method: 'POST',
            }),
            invalidatesTags: (_result, _error, name) => [deployListTag(name)],
        }),
        stopApp: build.mutation<void, string>({
            query: (name) => ({ url: `/apps/${encodeURIComponent(name)}/stop`, method: 'POST' }),
            invalidatesTags: (_result, _error, name) => [
                { type: 'App', id: name },
                deployListTag(name),
            ],
        }),
        startApp: build.mutation<Deploy, string>({
            query: (name) => ({ url: `/apps/${encodeURIComponent(name)}/start`, method: 'POST' }),
            invalidatesTags: (_result, _error, name) => [
                { type: 'App', id: name },
                deployListTag(name),
            ],
        }),
        rollbackDeploy: build.mutation<Deploy, DeployArgs>({
            query: ({ name, id }) => ({
                url: `/apps/${encodeURIComponent(name)}/deploys/${encodeURIComponent(id)}/rollback`,
                method: 'POST',
            }),
            invalidatesTags: (_result, _error, { name }) => [
                { type: 'App', id: name },
                deployListTag(name),
            ],
        }),
        getLogs: build.query<AppLogs, { name: string; tail: number }>({
            query: ({ name, tail }) => `/apps/${encodeURIComponent(name)}/logs?tail=${tail}`,
        }),
        getDeployHistory: build.infiniteQuery<CursorPage<Deploy>, string, string | null>({
            infiniteQueryOptions: {
                initialPageParam: null,
                getNextPageParam: (lastPage) => lastPage.next_cursor,
            },
            query: ({ queryArg: name, pageParam }) => {
                const params = new URLSearchParams({ limit: String(HISTORY_PAGE_SIZE) });
                if (pageParam) params.set('cursor', pageParam);
                return `/apps/${encodeURIComponent(name)}/deploys?${params}`;
            },
            providesTags: (_result, _error, name) => [deployListTag(name)],
        }),
        getDeploy: build.query<Deploy, DeployArgs>({
            query: ({ name, id }) =>
                `/apps/${encodeURIComponent(name)}/deploys/${encodeURIComponent(id)}`,
            // The list tag too: stop, start and rollback change a deploy they do not name.
            providesTags: (_result, _error, { name, id }) => [
                { type: 'Deploy', id },
                deployListTag(name),
            ],
        }),
    }),
});

export const {
    useStartDeployMutation,
    useStopAppMutation,
    useStartAppMutation,
    useRollbackDeployMutation,
    useGetLogsQuery,
    useGetDeployQuery,
    useGetDeployHistoryInfiniteQuery,
} = deploysApi;
