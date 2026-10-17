'use client';

import { useEffect, useRef } from 'react';
import { skipToken } from '@reduxjs/toolkit/query';
import { isDeployActive, isDeployFinished } from '@/shared/types';
import { normalizeError } from '@/shared/api';
import { useAppDispatch, useAppSelector } from '@/store/hooks';
import { deployListTag, deploysApi, useGetDeployQuery } from '../api/deploysApi';

const POLL_MS = 2000;

/** Polls a deploy every 2 s until it is running or failed (or no longer exists). */
export function useDeployPolling(name: string, id: string | null) {
    const args = id ? { name, id } : skipToken;

    const finished = useAppSelector((state) => {
        const { data, error } = deploysApi.endpoints.getDeploy.select(args)(state);
        if (data) return isDeployFinished(data.status);
        return error !== undefined && normalizeError(error).status === 404;
    });

    const query = useGetDeployQuery(args, { pollingInterval: finished ? 0 : POLL_MS });

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
