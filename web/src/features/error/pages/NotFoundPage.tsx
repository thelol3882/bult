import { ErrorScreen } from '../components/ErrorScreen';

export function NotFoundPage() {
    return (
        <ErrorScreen
            code="404"
            title="This page drifted away"
            actions={[
                { label: 'Home', href: '/', primary: true },
                { label: 'Open dashboard', href: '/apps' },
            ]}
        />
    );
}
