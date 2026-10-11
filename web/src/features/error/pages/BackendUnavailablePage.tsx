'use client';

import { ErrorScreen } from '../components/ErrorScreen';

interface BackendUnavailablePageProps {
    /** Defaults to a full page reload. */
    onRetry?: () => void;
}

export function BackendUnavailablePage({ onRetry }: BackendUnavailablePageProps) {
    return (
        <ErrorScreen
            code="503"
            title="Can't reach the API"
            description="The control plane is not responding."
            actions={[
                {
                    label: 'Try again',
                    primary: true,
                    onClick: onRetry ?? (() => window.location.reload()),
                },
            ]}
        />
    );
}
