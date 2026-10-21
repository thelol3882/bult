'use client';

import { useEffect, useRef } from 'react';
import { skipToken } from '@reduxjs/toolkit/query';
import { isDeployActive, isDeployFinished } from '@/shared/types';
import { normalizeError } from '@/shared/api';
import { useAppDispatch, useAppSelector } from '@/store/hooks';
import { deployListTag, deploysApi, useGetDeployQuery } from '../api/deploysApi';

const POLL_MS = 2000;
// A running deploy still changes: a replica fails its health check, a node dies, a scale adds replicas.
const RUNNING_POLL_MS = 5000;

/** Polls a deploy every 2 s while it is in progress, every 5 s while it runs, never once final. */
export function useDeployPolling(name: string, id: string | null) {
    const args = id ? { name, id } : skipToken;

    const pollingInterval = useAppSelector((state) => {
        const { data, error } = deploysApi.endpoints.getDeploy.select(args)(state);
        if (data) {
            if (data.status === 'running') return RUNNING_POLL_MS;
            return isDeployFinished(data.status) ? 0 : POLL_MS;
        }
        return error !== undefined && normalizeError(error).status === 404 ? 0 : POLL_MS;
    });

    const query = useGetDeployQuery(args, { pollingInterval, skipPollingIfUnfocused: true });

    // A deploy that just finished changed its neighbours too (a redeploy supersedes the old one).
    const dispatch = useAppDispatch();
    const status = query.data?.status;
    const previous = useRef(status);
    useEffect(() => {
        const was = previous.current;
        previous.current = status;
        if (was && status && isDeployActive(was) && isDeployFinished(status)) {
            dispatch(deploysApi.util.invalidateTags([deployListTag(name)]));
        }
    }, [status, name, dispatch]);

    return {
        deploy: query.data,
        error: query.error ? normalizeError(query.error) : undefined,
        isLoading: query.isLoading,
    };
}
