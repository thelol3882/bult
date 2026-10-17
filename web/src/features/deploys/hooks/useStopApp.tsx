'use client';

import { Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { normalizeError } from '@/shared/api';
import { showError, showSuccess, showWarning } from '@/shared/utils/notifications';
import { useStopAppMutation } from '../api/deploysApi';

/** Returns a function that asks for confirmation, then stops the app. */
export function useStopApp() {
    const [stopApp] = useStopAppMutation();

    return (name: string) =>
        modals.openConfirmModal({
            title: 'Stop app',
            centered: true,
            children: (
                <Text size="sm">
                    Stop <b>{name}</b>? Its URL will show a &quot;stopped&quot; page until you start
                    it again. Start reuses the last image, so nothing is rebuilt.
                </Text>
            ),
            labels: { confirm: 'Stop', cancel: 'Cancel' },
            confirmProps: { color: 'red' },
            onConfirm: async () => {
                try {
                    await stopApp(name).unwrap();
                    showSuccess(`${name} was stopped`);
                } catch (e) {
                    const error = normalizeError(e);
                    if (error.code === 'deploy_in_progress') {
                        showWarning(
                            'This app has a deploy in progress. Wait for it to finish.',
                            'Deploy in progress',
                        );
                        return;
                    }
                    showError(error.message, 'Could not stop app', error.traceId);
                }
            },
        });
}
