'use client';

import { useRouter } from 'next/navigation';
import { baseApi } from '@/shared/api';
import { useAppDispatch } from '@/store/hooks';
import { bffRequest } from '../services/bff';

export function useLogout() {
    const router = useRouter();
    const dispatch = useAppDispatch();

    return async () => {
        await bffRequest('logout', 'POST');
        dispatch(baseApi.util.resetApiState());
        router.replace('/login');
        router.refresh();
    };
}
