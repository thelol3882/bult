'use client';

import { normalizeError } from '@/shared/api';
import { showError, showSuccess, showWarning } from '@/shared/utils/notifications';
import { useSetReplicasMutation } from '../api/deploysApi';
import { scaleErrorMessage } from '../services/replicas';

/**
 * Changes the number of replicas. Resolves with the id of the deploy that starts a stopped app
 * (the page should follow it), or null when no new deploy was made or the request failed.
 */
export function useSetReplicas() {
    const [setReplicas, state] = useSetReplicasMutation();

    const scale = async (name: string, replicas: number): Promise<string | null> => {
        try {
            const result = await setReplicas({ name, replicas }).unwrap();
            showSuccess(
                replicas === 0 ? `${name} was stopped` : `${name} now has ${replicas} replica(s)`,
            );
            return result.deploy?.status === 'starting' ? result.deploy.id : null;
        } catch (e) {
            const error = normalizeError(e);
            const known = scaleErrorMessage(error.code);
            if (known !== undefined) {
                showWarning(known, 'Cannot change replicas');
                return null;
            }
            showError(error.message, 'Could not change replicas', error.traceId);
            return null;
        }
    };

    return { scale, isScaling: state.isLoading };
}
