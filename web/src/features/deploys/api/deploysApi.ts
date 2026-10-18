import { baseApi } from '@/shared/api';
import type { CursorPage } from '@/shared/types';
import type { AppLogs, Deploy, DeployArgs, ReplicasResult, SetReplicasArgs } from '../types';

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
        setReplicas: build.mutation<ReplicasResult, SetReplicasArgs>({
            query: ({ name, replicas }) => ({
                url: `/apps/${encodeURIComponent(name)}/replicas`,
                method: 'PUT',
                body: { replicas },
            }),
            // The deploy list tag also refetches the polled deploy (its replicas changed).
            invalidatesTags: (_result, _error, { name }) => [
                { type: 'App', id: name },
                deployListTag(name),
            ],
        }),
        cancelDeploy: build.mutation<Deploy, DeployArgs>({
            query: ({ name, id }) => ({
                url: `/apps/${encodeURIComponent(name)}/deploys/${encodeURIComponent(id)}/cancel`,
                method: 'POST',
            }),
            // The deploy itself too: a building one is finished by the worker a moment later.
            invalidatesTags: (_result, _error, { name, id }) => [
                { type: 'Deploy', id },
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
        getLogs: build.query<AppLogs, { name: string; tail: number; replica?: number }>({
            query: ({ name, tail, replica }) => {
                const params = new URLSearchParams({ tail: String(tail) });
                if (replica !== undefined) params.set('replica', String(replica));
                return `/apps/${encodeURIComponent(name)}/logs?${params}`;
            },
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
    useSetReplicasMutation,
    useCancelDeployMutation,
    useRollbackDeployMutation,
    useGetLogsQuery,
    useGetDeployQuery,
    useGetDeployHistoryInfiniteQuery,
} = deploysApi;
