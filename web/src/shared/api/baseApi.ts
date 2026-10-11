import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';

// All calls go through the Next.js rewrite /api/* -> control plane, so the browser stays same-origin.
export const baseApi = createApi({
    reducerPath: 'api',
    baseQuery: fetchBaseQuery({ baseUrl: '/api' }),
    tagTypes: ['App', 'Deploy'],
    endpoints: () => ({}),
});
