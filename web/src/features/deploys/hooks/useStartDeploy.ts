'use client';

import { normalizeError } from '@/shared/api';
import { showError } from '@/shared/utils/notifications';
import { useStartDeployMutation } from '../api/deploysApi';

/** Starts a deploy and resolves with its id; errors are shown as a notification. */
export function useStartDeploy() {
    const [start, state] = useStartDeployMutation();

    const deploy = async (name: string): Promise<string | null> => {
        try {
            return (await start(name).unwrap()).id;
        } catch (e) {
            const error = normalizeError(e);
            showError(error.message, 'Deploy failed to start', error.traceId);
            return null;
        }
    };

    return { deploy, isStarting: state.isLoading };
}
