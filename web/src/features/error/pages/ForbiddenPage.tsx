import { ErrorScreen } from '../components/ErrorScreen';

export function ForbiddenPage() {
    return (
        <ErrorScreen
            code="403"
            title="This app belongs to another account"
            description="You are logged in, but you do not have access to it."
            actions={[{ label: 'Back to my apps', href: '/apps', primary: true }]}
        />
    );
}
