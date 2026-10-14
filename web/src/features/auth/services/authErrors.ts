import type { ApiError } from '@/shared/api';

export interface AuthFormErrors {
    fieldErrors?: Record<string, string>;
    formError?: string;
}

/** Field errors go under their inputs; everything else becomes one message above the form. */
export function mapAuthError(error: ApiError): AuthFormErrors {
    if (error.code === 'invalid_credentials') {
        return { formError: 'Incorrect email or password' };
    }
    if (error.fieldErrors && Object.keys(error.fieldErrors).length > 0) {
        return { fieldErrors: error.fieldErrors };
    }
    if (error.status === 'network') return { formError: 'Cannot reach the server. Try again.' };
    return { formError: error.message };
}
