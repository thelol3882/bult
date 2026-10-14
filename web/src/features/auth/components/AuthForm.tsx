'use client';

import { useState } from 'react';
import { Alert, Button, PasswordInput, Stack, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';
import { useAuthSubmit } from '../hooks/useAuthSubmit';
import type { AuthCredentials } from '../types';

interface AuthFormProps {
    mode: 'login' | 'register';
    next: string;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function AuthForm({ mode, next }: AuthFormProps) {
    const isRegister = mode === 'register';
    const { submit, isLoading } = useAuthSubmit(mode, next);
    const [formError, setFormError] = useState<string | null>(null);

    const form = useForm<AuthCredentials>({
        mode: 'controlled',
        initialValues: { email: '', password: '' },
        validate: {
            email: (v) => (EMAIL_RE.test(v.trim()) ? null : 'Enter a valid email'),
            password: (v) =>
                isRegister && v.length < 8
                    ? 'At least 8 characters'
                    : v.length === 0
                      ? 'Password is required'
                      : null,
        },
    });

    const handleSubmit = async (values: AuthCredentials) => {
        setFormError(null);
        const { fieldErrors, formError: general } = await submit({
            email: values.email.trim(),
            password: values.password,
        });
        if (fieldErrors) form.setErrors(fieldErrors);
        if (general) setFormError(general);
    };

    return (
        <form onSubmit={form.onSubmit(handleSubmit)} noValidate>
            <Stack gap="md">
                {formError && (
                    <Alert color="red" variant="light" role="alert">
                        {formError}
                    </Alert>
                )}
                <TextInput
                    label="Email"
                    type="email"
                    placeholder="you@example.com"
                    autoComplete="email"
                    withAsterisk
                    {...form.getInputProps('email')}
                />
                <PasswordInput
                    label="Password"
                    description={isRegister ? 'At least 8 characters' : undefined}
                    autoComplete={isRegister ? 'new-password' : 'current-password'}
                    withAsterisk
                    {...form.getInputProps('password')}
                />
                <Button type="submit" loading={isLoading} fullWidth mt="xs">
                    {isRegister ? 'Create account' : 'Log in'}
                </Button>
            </Stack>
        </form>
    );
}
