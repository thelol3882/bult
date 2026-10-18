import { baseApi } from '@/shared/api';
import type { PlatformNode } from '../types';

export const nodesApi = baseApi.injectEndpoints({
    endpoints: (build) => ({
        getNodes: build.query<PlatformNode[], void>({
            query: () => '/nodes',
        }),
    }),
});

export const { useGetNodesQuery } = nodesApi;
