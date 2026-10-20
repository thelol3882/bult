import type { Metadata } from 'next';
import { Bricolage_Grotesque, JetBrains_Mono, Onest } from 'next/font/google';
import { ColorSchemeScript, mantineHtmlProps } from '@mantine/core';
import { Providers } from './providers';

import '@mantine/core/styles.css';
import '@mantine/charts/styles.css';
import '@mantine/notifications/styles.css';
import '@mantine/nprogress/styles.css';
import '@/theme/tokens.css';
import '@/theme/global.css';

const onest = Onest({ subsets: ['latin'], variable: '--font-sans', display: 'swap' });
const bricolage = Bricolage_Grotesque({
    subsets: ['latin'],
    axes: ['opsz'],
    variable: '--font-display',
    display: 'swap',
});
const jetbrains = JetBrains_Mono({ subsets: ['latin'], variable: '--font-mono', display: 'swap' });

export const metadata: Metadata = {
    title: { default: 'bult', template: '%s · bult' },
    description: 'From git push to a live URL.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
    return (
        <html
            lang="en"
            {...mantineHtmlProps}
            className={`${onest.variable} ${bricolage.variable} ${jetbrains.variable}`}
        >
            <head>
                <ColorSchemeScript defaultColorScheme="light" />
            </head>
            <body>
                <Providers>{children}</Providers>
            </body>
        </html>
    );
}
