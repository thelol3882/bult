'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { bffRequest } from '../services/bff';
import { mapAuthError, type AuthFormErrors } from '../services/authErrors';
import type { AuthCredentials } from '../types';

/** Shared by login and register: posts credentials, then navigates to `next`. */
export function useAuthSubmit(endpoint: 'login' | 'register', next: string) {
    const router = useRouter();
    const [isLoading, setLoading] = useState(false);

    const submit = async (values: AuthCredentials): Promise<AuthFormErrors> => {
        setLoading(true);
        const result = await bffRequest(endpoint, 'POST', values);
        if (!result.ok) {
            setLoading(false);
            return mapAuthError(result.error);
        }
        router.replace(next);
        router.refresh();
        return {};
    };

    return { submit, isLoading };
}
