'use client';

import { useEffect, useRef, type ReactNode } from 'react';
import { Provider } from 'react-redux';
import { setupListeners } from '@reduxjs/toolkit/query';
import { makeStore, type AppStore } from './index';

export function StoreProvider({ children }: { children: ReactNode }) {
    const storeRef = useRef<AppStore | null>(null);
    // One store per provider instance (not a module singleton), created lazily.
    storeRef.current ??= makeStore();
    // eslint-disable-next-line react-hooks/refs
    const store = storeRef.current;

    useEffect(() => setupListeners(store.dispatch), [store]);

    return <Provider store={store}>{children}</Provider>;
}
