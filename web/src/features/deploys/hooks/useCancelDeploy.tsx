'use client';

import { Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { normalizeError } from '@/shared/api';
import { showError, showWarning } from '@/shared/utils/notifications';
import { useCancelDeployMutation } from '../api/deploysApi';
import type { Deploy } from '../types';

/** Returns a function that asks for confirmation, then cancels a queued or building deploy. */
export function useCancelDeploy() {
    const [cancelDeploy] = useCancelDeployMutation();

    return (deploy: Deploy) =>
        modals.openConfirmModal({
            title: 'Cancel deploy',
            centered: true,
            children: (
                <Text size="sm">
                    Stop this deploy? The build is aborted and nothing new is started. The running
                    version of the app, if any, keeps serving.
                </Text>
            ),
            labels: { confirm: 'Cancel deploy', cancel: 'Keep going' },
            confirmProps: { color: 'red' },
            onConfirm: async () => {
                try {
                    await cancelDeploy({ name: deploy.app_name, id: deploy.id }).unwrap();
                } catch (e) {
                    const error = normalizeError(e);
                    if (error.code === 'deploy_not_cancellable') {
                        showWarning(error.message, 'Cannot cancel');
                        return;
                    }
                    showError(error.message, 'Could not cancel the deploy', error.traceId);
                }
            },
        });
}
