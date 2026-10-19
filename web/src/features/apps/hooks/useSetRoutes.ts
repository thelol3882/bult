'use client';

import { normalizeError } from '@/shared/api';
import { showError, showSuccess } from '@/shared/utils/notifications';
import { useSetRoutesMutation } from '../api/appsApi';
import type { AppRoute } from '../types';

export interface SetRoutesResult {
    ok: boolean;
    /** The API's message when it rejected the list itself (target, ownership, validation). */
    routesError?: string;
}

export function useSetRoutes() {
    const [setRoutes, state] = useSetRoutesMutation();

    const submit = async (name: string, routes: AppRoute[]): Promise<SetRoutesResult> => {
        try {
            await setRoutes({ name, routes }).unwrap();
            showSuccess('Routes saved.');
            return { ok: true };
        } catch (e) {
            const error = normalizeError(e);
            // 403/404/422 are about what the user typed: show them in the form.
            if (error.status === 403 || error.status === 404 || error.status === 422) {
                const fields = Object.values(error.fieldErrors ?? {});
                return {
                    ok: false,
                    routesError: fields.length > 0 ? fields.join(' ') : error.message,
                };
            }
            showError(error.message, 'Could not save routes', error.traceId);
            return { ok: false };
        }
    };

    return { submit, isLoading: state.isLoading };
}
