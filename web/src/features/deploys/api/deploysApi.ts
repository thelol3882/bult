import { baseApi } from '@/shared/api';
import type { Deploy, DeployArgs } from '../types';

export const deploysApi = baseApi.injectEndpoints({
    endpoints: (build) => ({
        startDeploy: build.mutation<Deploy, string>({
            query: (name) => ({
                url: `/apps/${encodeURIComponent(name)}/deploys`,
                method: 'POST',
            }),
        }),
        getDeploy: build.query<Deploy, DeployArgs>({
            query: ({ name, id }) =>
                `/apps/${encodeURIComponent(name)}/deploys/${encodeURIComponent(id)}`,
            providesTags: (_result, _error, { id }) => [{ type: 'Deploy', id }],
        }),
    }),
});

export const { useStartDeployMutation, useGetDeployQuery } = deploysApi;
