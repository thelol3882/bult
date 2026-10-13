import { baseApi } from '@/shared/api';
import type { CursorPage } from '@/shared/types';
import type { Deploy, DeployArgs } from '../types';

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
            providesTags: (_result, _error, { id }) => [{ type: 'Deploy', id }],
        }),
    }),
});

export const { useStartDeployMutation, useGetDeployQuery, useGetDeployHistoryInfiniteQuery } =
    deploysApi;
