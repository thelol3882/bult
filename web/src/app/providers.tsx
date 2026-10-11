'use client';

import type { ReactNode } from 'react';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { NavigationProgress } from '@mantine/nprogress';
import { Notifications } from '@mantine/notifications';
import { NuqsAdapter } from 'nuqs/adapters/next/app';
import { RouteProgress } from '@/shared/components/RouteProgress';
import { StoreProvider } from '@/store/StoreProvider';
import { bultTheme } from '@/theme';

export function Providers({ children }: { children: ReactNode }) {
    return (
        <StoreProvider>
            <MantineProvider theme={bultTheme} defaultColorScheme="light">
                <NavigationProgress />
                <RouteProgress />
                <Notifications position="top-right" />
                <ModalsProvider>
                    <NuqsAdapter>{children}</NuqsAdapter>
                </ModalsProvider>
            </MantineProvider>
        </StoreProvider>
    );
}
