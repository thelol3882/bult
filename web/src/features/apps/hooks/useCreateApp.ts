'use client';

import { normalizeError, type ApiError } from '@/shared/api';
import { showError } from '@/shared/utils/notifications';
import { useCreateAppMutation } from '../api/appsApi';
import type { AppCreate, BultApp } from '../types';

export interface CreateAppResult {
    app?: BultApp;
    fieldErrors?: Record<string, string>;
}

export function useCreateApp() {
    const [createApp, state] = useCreateAppMutation();

    const submit = async (values: AppCreate): Promise<CreateAppResult> => {
        try {
            return { app: await createApp(values).unwrap() };
        } catch (e) {
            const error: ApiError = normalizeError(e);
            if (error.status === 409) return { fieldErrors: { name: error.message } };
            if (error.fieldErrors && Object.keys(error.fieldErrors).length > 0) {
                return { fieldErrors: error.fieldErrors };
            }
            showError(error.message, 'Could not create app');
            return {};
        }
    };

    return { submit, isLoading: state.isLoading };
}
