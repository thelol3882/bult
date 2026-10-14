import { createApi, fetchBaseQuery, type BaseQueryFn } from '@reduxjs/toolkit/query/react';

const AUTH_PAGES = ['/login', '/register'];

// All calls go through the /api route handler, which adds the session's bearer token server-side.
const rawBaseQuery = fetchBaseQuery({ baseUrl: '/api' });

const baseQuery: BaseQueryFn = async (args, api, extra) => {
    const result = await rawBaseQuery(args, api, extra);
    if (result.error?.status === 401 && typeof window !== 'undefined') {
        const { pathname, search } = window.location;
        if (!AUTH_PAGES.includes(pathname)) {
            const target = new URL('/login', window.location.origin);
            target.searchParams.set('next', `${pathname}${search}`);
            window.location.assign(target);
        }
    }
    return result;
};

export const baseApi = createApi({
    reducerPath: 'api',
    baseQuery,
    tagTypes: ['App', 'Deploy'],
    endpoints: () => ({}),
});
