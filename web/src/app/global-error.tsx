'use client';

import { Bricolage_Grotesque, Onest } from 'next/font/google';
import { ErrorScreen } from '@/features/error';

import '@/theme/tokens.css';
import '@/theme/global.css';

// global-error replaces the root layout, so fonts and styles are set up again here (no Mantine).
const onest = Onest({ subsets: ['latin'], variable: '--font-sans', display: 'swap' });
const bricolage = Bricolage_Grotesque({
    subsets: ['latin'],
    axes: ['opsz'],
    variable: '--font-display',
    display: 'swap',
});

export default function GlobalError({
    reset,
}: {
    error: Error & { digest?: string };
    reset: () => void;
}) {
    return (
        <html lang="en" className={`${onest.variable} ${bricolage.variable}`}>
            <body>
                <ErrorScreen
                    code="500"
                    title="Something went wrong"
                    actions={[{ label: 'Try again', primary: true, onClick: reset }]}
                />
            </body>
        </html>
    );
}
