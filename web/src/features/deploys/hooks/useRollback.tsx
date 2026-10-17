'use client';

import { Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { normalizeError } from '@/shared/api';
import { showError, showWarning } from '@/shared/utils/notifications';
import { shortSha } from '@/shared/utils/digest';
import { useRollbackDeployMutation } from '../api/deploysApi';
import type { Deploy } from '../types';

/** Returns a function that asks for confirmation, then runs the image of an earlier deploy. */
export function useRollback(onStarted: (deployId: string) => void) {
    const [rollback] = useRollbackDeployMutation();

    return (deploy: Deploy) =>
        modals.openConfirmModal({
            title: 'Roll back',
            centered: true,
            children: (
                <Text size="sm">
                    Run the image of{' '}
                    {deploy.commit_sha ? <b>{shortSha(deploy.commit_sha)}</b> : 'this deploy'}{' '}
                    again? A new deploy replaces the running one. Nothing is rebuilt.
                </Text>
            ),
            labels: { confirm: 'Roll back', cancel: 'Cancel' },
            onConfirm: async () => {
                try {
                    const created = await rollback({
                        name: deploy.app_name,
                        id: deploy.id,
                    }).unwrap();
                    onStarted(created.id);
                } catch (e) {
                    const error = normalizeError(e);
                    if (
                        error.code === 'deploy_in_progress' ||
                        error.code === 'deploy_not_restorable'
                    ) {
                        showWarning(error.message, 'Cannot roll back');
                        return;
                    }
                    showError(error.message, 'Could not roll back', error.traceId);
                }
            },
        });
}
