'use client';

import { normalizeError } from '@/shared/api';
import { showError } from '@/shared/utils/notifications';
import { useUpdateAppMutation } from '../api/appsApi';
import type { AppUpdate, BultApp } from '../types';

export interface UpdateAppResult {
    app?: BultApp;
    fieldErrors?: Record<string, string>;
}

export function useUpdateApp() {
    const [updateApp, state] = useUpdateAppMutation();

    const submit = async (name: string, patch: AppUpdate): Promise<UpdateAppResult> => {
        try {
            return { app: await updateApp({ name, patch }).unwrap() };
        } catch (e) {
            const error = normalizeError(e);
            if (error.fieldErrors && Object.keys(error.fieldErrors).length > 0) {
                return { fieldErrors: error.fieldErrors };
            }
            showError(error.message, 'Could not update app', error.traceId);
            return {};
        }
    };

    return { submit, isLoading: state.isLoading };
}
