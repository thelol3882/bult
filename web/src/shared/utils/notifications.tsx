import { Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';

/** `traceId`: the API's request id, shown as a small muted line so users can quote it. */
export function showError(message: string, title = 'Something went wrong', traceId?: string) {
    notifications.show({
        title,
        message: traceId ? (
            <>
                {message}
                <Text size="xs" c="dimmed" mt={4}>
                    Trace: {traceId}
                </Text>
            </>
        ) : (
            message
        ),
        color: 'red',
        autoClose: 6000,
    });
}

export function showWarning(message: string, title: string) {
    notifications.show({ title, message, color: 'yellow', autoClose: 6000 });
}

export function showSuccess(message: string, title = 'Done') {
    notifications.show({ title, message, color: 'green' });
}
