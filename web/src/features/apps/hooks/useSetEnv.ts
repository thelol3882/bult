'use client';

import { normalizeError } from '@/shared/api';
import { showError, showSuccess } from '@/shared/utils/notifications';
import { useSetEnvMutation } from '../api/appsApi';
import type { EnvMap } from '../types';

export interface SetEnvResult {
    ok: boolean;
    /** The API's message when it rejected the map itself (limits, reserved names). */
    envError?: string;
}

export function useSetEnv() {
    const [setEnv, state] = useSetEnvMutation();

    const submit = async (name: string, env: EnvMap): Promise<SetEnvResult> => {
        try {
            await setEnv({ name, env }).unwrap();
            showSuccess('Variables saved. They apply on the next deploy.');
            return { ok: true };
        } catch (e) {
            const error = normalizeError(e);
            const envError = error.fieldErrors?.env;
            if (envError) return { ok: false, envError };
            showError(error.message, 'Could not save variables', error.traceId);
            return { ok: false };
        }
    };

    return { submit, isLoading: state.isLoading };
}
