import { baseApi } from '@/shared/api';
import type { Page } from '@/shared/types';
import type { AppCreate, AppUpdate, BultApp, EnvMap } from '../types';

export const APPS_PAGE_SIZE = 20;

export const appsApi = baseApi.injectEndpoints({
    endpoints: (build) => ({
        getApps: build.query<Page<BultApp>, number>({
            query: (page) => `/apps?page=${page}&page_size=${APPS_PAGE_SIZE}`,
            providesTags: (result) => [
                { type: 'App', id: 'LIST' },
                ...(result?.results ?? []).map(({ name }) => ({ type: 'App' as const, id: name })),
            ],
        }),
        getApp: build.query<BultApp, string>({
            query: (name) => `/apps/${encodeURIComponent(name)}`,
            providesTags: (_result, _error, name) => [{ type: 'App', id: name }],
        }),
        createApp: build.mutation<BultApp, AppCreate>({
            query: (body) => ({ url: '/apps', method: 'POST', body }),
            // Also drops any stale cached detail for a re-created name.
            invalidatesTags: (app) => [
                { type: 'App', id: 'LIST' },
                ...(app ? [{ type: 'App' as const, id: app.name }] : []),
            ],
        }),
        updateApp: build.mutation<BultApp, { name: string; patch: AppUpdate }>({
            query: ({ name, patch }) => ({
                url: `/apps/${encodeURIComponent(name)}`,
                method: 'PATCH',
                body: patch,
            }),
            invalidatesTags: (_result, _error, { name }) => [
                { type: 'App', id: name },
                { type: 'App', id: 'LIST' },
            ],
        }),
        setEnv: build.mutation<BultApp, { name: string; env: EnvMap }>({
            query: ({ name, env }) => ({
                url: `/apps/${encodeURIComponent(name)}/env`,
                method: 'PUT',
                body: { env },
            }),
            invalidatesTags: (_result, _error, { name }) => [{ type: 'App', id: name }],
        }),
        deleteApp: build.mutation<void, string>({
            query: (name) => ({ url: `/apps/${encodeURIComponent(name)}`, method: 'DELETE' }),
            // List only: invalidating the app's own tag would refetch it (404).
            invalidatesTags: [{ type: 'App', id: 'LIST' }],
        }),
    }),
});

export const {
    useGetAppsQuery,
    useGetAppQuery,
    useCreateAppMutation,
    useUpdateAppMutation,
    useSetEnvMutation,
    useDeleteAppMutation,
} = appsApi;
