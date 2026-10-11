'use client';

import { Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { normalizeError } from '@/shared/api';
import { showError, showSuccess } from '@/shared/utils/notifications';
import { useDeleteAppMutation } from '../api/appsApi';

/** Returns a function that asks for confirmation, then deletes the app. */
export function useDeleteApp(onDeleted?: (name: string) => void) {
    const [deleteApp] = useDeleteAppMutation();

    return (name: string) =>
        modals.openConfirmModal({
            title: 'Delete app',
            centered: true,
            children: (
                <Text size="sm">
                    Delete <b>{name}</b>? Its URL will stop working. This cannot be undone.
                </Text>
            ),
            labels: { confirm: 'Delete', cancel: 'Cancel' },
            confirmProps: { color: 'red' },
            onConfirm: async () => {
                try {
                    await deleteApp(name).unwrap();
                    showSuccess(`${name} was deleted`);
                    onDeleted?.(name);
                } catch (e) {
                    showError(normalizeError(e).message, 'Could not delete app');
                }
            },
        });
}
