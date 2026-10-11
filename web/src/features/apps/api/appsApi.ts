import { baseApi } from '@/shared/api';
import type { AppCreate, BultApp } from '../types';

export const appsApi = baseApi.injectEndpoints({
    endpoints: (build) => ({
        getApps: build.query<BultApp[], void>({
            query: () => '/apps',
            providesTags: (result) => [
                { type: 'App', id: 'LIST' },
                ...(result ?? []).map(({ name }) => ({ type: 'App' as const, id: name })),
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
        deleteApp: build.mutation<void, string>({
            query: (name) => ({ url: `/apps/${encodeURIComponent(name)}`, method: 'DELETE' }),
            // List only: invalidating the app's own tag would refetch it (404).
            invalidatesTags: [{ type: 'App', id: 'LIST' }],
        }),
    }),
});

export const { useGetAppsQuery, useGetAppQuery, useCreateAppMutation, useDeleteAppMutation } =
    appsApi;
