'use client';

import { useRouter } from 'next/navigation';
import { Button, Card, Group, SegmentedControl, Stack, TextInput, Text } from '@mantine/core';
import { useForm } from '@mantine/form';
import { useCreateApp } from '../hooks/useCreateApp';
import { validateAppName, validateRepoUrl } from '../services/validators';
import type { AppCreate } from '../types';

export function AppForm() {
    const router = useRouter();
    const { submit, isLoading } = useCreateApp();

    const form = useForm<AppCreate>({
        mode: 'controlled',
        initialValues: { name: '', preset: 'fastapi', repo_url: '', branch: 'main', subdir: '' },
        validate: {
            name: validateAppName,
            repo_url: validateRepoUrl,
            branch: (value) => (value.trim() ? null : 'Branch is required'),
        },
    });

    const handleSubmit = async (values: AppCreate) => {
        const result = await submit({
            ...values,
            repo_url: values.repo_url.trim(),
            branch: values.branch.trim(),
            subdir: values.subdir.trim(),
        });
        if (result.fieldErrors) form.setErrors(result.fieldErrors);
        if (result.app) router.push(`/apps/${result.app.name}`);
    };

    return (
        <Card maw={560}>
            <form onSubmit={form.onSubmit(handleSubmit)} noValidate>
                <Stack gap="md">
                    <TextInput
                        label="App name"
                        description="Lowercase letters, digits and hyphens. Becomes your subdomain."
                        placeholder="blog"
                        rightSection={
                            <Text size="xs" c="gray.6" pr="xs" style={{ whiteSpace: 'nowrap' }}>
                                .bult.localhost
                            </Text>
                        }
                        rightSectionWidth={118}
                        autoComplete="off"
                        withAsterisk
                        {...form.getInputProps('name')}
                    />
                    <div>
                        <Text size="sm" fw={500} mb={6}>
                            Preset
                        </Text>
                        <SegmentedControl
                            data={[
                                { label: 'fastapi', value: 'fastapi' },
                                { label: 'express', value: 'express' },
                            ]}
                            {...form.getInputProps('preset')}
                        />
                    </div>
                    <TextInput
                        label="Repository URL"
                        placeholder="https://github.com/user/repo"
                        autoComplete="off"
                        withAsterisk
                        {...form.getInputProps('repo_url')}
                    />
                    <Group grow align="flex-start">
                        <TextInput
                            label="Branch"
                            placeholder="main"
                            {...form.getInputProps('branch')}
                        />
                        <TextInput
                            label="Subdirectory"
                            placeholder="examples/fastapi-hello"
                            {...form.getInputProps('subdir')}
                        />
                    </Group>
                    <Group justify="flex-end" mt="xs">
                        <Button variant="default" onClick={() => router.push('/apps')}>
                            Cancel
                        </Button>
                        <Button type="submit" loading={isLoading}>
                            Create app
                        </Button>
                    </Group>
                </Stack>
            </form>
        </Card>
    );
}
