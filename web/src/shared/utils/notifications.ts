import { notifications } from '@mantine/notifications';

export function showError(message: string, title = 'Something went wrong') {
    notifications.show({ title, message, color: 'red', autoClose: 6000 });
}

export function showSuccess(message: string, title = 'Done') {
    notifications.show({ title, message, color: 'green' });
}
