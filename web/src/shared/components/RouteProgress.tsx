'use client';

import { useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { nprogress } from '@mantine/nprogress';

/** Drives the top progress bar: starts on internal link clicks, completes when the route changes. */
export function RouteProgress() {
    const pathname = usePathname();

    useEffect(() => {
        nprogress.complete();
    }, [pathname]);

    useEffect(() => {
        const onClick = (event: MouseEvent) => {
            if (
                event.defaultPrevented ||
                event.button !== 0 ||
                event.metaKey ||
                event.ctrlKey ||
                event.shiftKey ||
                event.altKey
            ) {
                return;
            }
            const anchor = (event.target as Element | null)?.closest('a');
            const href = anchor?.getAttribute('href');
            if (!anchor || !href || !href.startsWith('/')) return;
            if (anchor.target === '_blank' || anchor.hasAttribute('download')) return;
            if (href.split(/[?#]/)[0] !== window.location.pathname) nprogress.start();
        };
        document.addEventListener('click', onClick);
        return () => document.removeEventListener('click', onClick);
    }, []);

    return null;
}
