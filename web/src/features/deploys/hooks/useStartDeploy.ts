'use client';

import { normalizeError } from '@/shared/api';
import { showError, showWarning } from '@/shared/utils/notifications';
import { useStartDeployMutation } from '../api/deploysApi';

/** Queues a deploy and resolves with its id; errors are shown as a notification. */
export function useStartDeploy() {
    const [start, state] = useStartDeployMutation();

    const deploy = async (name: string): Promise<string | null> => {
        try {
            return (await start(name).unwrap()).id;
        } catch (e) {
            const error = normalizeError(e);
            if (error.code === 'deploy_in_progress') {
                showWarning(
                    'This app already has a deploy in progress. Wait for it to finish.',
                    'Deploy in progress',
                );
                return null;
            }
            showError(error.message, 'Deploy failed to start', error.traceId);
            return null;
        }
    };

    return { deploy, isStarting: state.isLoading };
}
