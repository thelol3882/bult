'use client';

import { normalizeError } from '@/shared/api';
import { showError, showWarning } from '@/shared/utils/notifications';
import { useStartAppMutation } from '../api/deploysApi';

/** Starts a stopped app from its last image; resolves with the new deploy's id. */
export function useStartApp() {
    const [start, state] = useStartAppMutation();

    const startApp = async (name: string): Promise<string | null> => {
        try {
            return (await start(name).unwrap()).id;
        } catch (e) {
            const error = normalizeError(e);
            if (error.code === 'deploy_in_progress' || error.code === 'nothing_to_start') {
                showWarning(error.message, 'Cannot start');
                return null;
            }
            showError(error.message, 'Could not start app', error.traceId);
            return null;
        }
    };

    return { startApp, isStarting: state.isLoading };
}
