'use client';

import { Button, Group, Modal, SegmentedControl, Stack, Text, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';
import { useUpdateApp } from '../hooks/useUpdateApp';
import { HEALTH_PATH_HELP, validateHealthPath, validateRepoUrl } from '../services/validators';
import type { AppUpdate, BultApp } from '../types';

type Values = Required<AppUpdate>;

interface EditAppModalProps {
    app: BultApp;
    opened: boolean;
    onClose: () => void;
}

export function EditAppModal({ app, opened, onClose }: EditAppModalProps) {
    return (
        <Modal opened={opened} onClose={onClose} title={`Edit ${app.name}`} centered>
            <EditAppForm app={app} onClose={onClose} />
        </Modal>
    );
}

// Mounted only while the modal is open, so the form always starts from the current values.
function EditAppForm({ app, onClose }: { app: BultApp; onClose: () => void }) {
    const { submit, isLoading } = useUpdateApp();

    const initial: Values = {
        preset: app.preset,
        repo_url: app.repo_url,
        branch: app.branch,
        subdir: app.subdir,
        health_path: app.health_path,
    };

    const form = useForm<Values>({
        mode: 'controlled',
        initialValues: initial,
        validate: {
            repo_url: validateRepoUrl,
            health_path: validateHealthPath,
            branch: (value) => (value.trim() ? null : 'Branch is required'),
        },
    });

    const handleSubmit = async (values: Values) => {
        const next: Values = {
            preset: values.preset,
            repo_url: values.repo_url.trim(),
            branch: values.branch.trim(),
            subdir: values.subdir.trim(),
            health_path: values.health_path.trim(),
        };
        // Send only the fields that changed.
        const patch: AppUpdate = {};
        if (next.preset !== initial.preset) patch.preset = next.preset;
        if (next.repo_url !== initial.repo_url) patch.repo_url = next.repo_url;
        if (next.branch !== initial.branch) patch.branch = next.branch;
        if (next.subdir !== initial.subdir) patch.subdir = next.subdir;
        // An empty string clears the path (back to the TCP check).
        if (next.health_path !== initial.health_path) patch.health_path = next.health_path;

        if (Object.keys(patch).length === 0) {
            onClose();
            return;
        }
        const result = await submit(app.name, patch);
        if (result.fieldErrors) form.setErrors(result.fieldErrors);
        if (result.app) onClose();
    };

    return (
        <form onSubmit={form.onSubmit(handleSubmit)} noValidate>
            <Stack gap="md">
                <div>
                    <Text size="sm" fw={500} mb={6}>
                        Preset
                    </Text>
                    <SegmentedControl
                        data={[
                            { label: 'fastapi', value: 'fastapi' },
                            { label: 'express', value: 'express' },
                            { label: 'static', value: 'static' },
                        ]}
                        {...form.getInputProps('preset')}
                    />
                </div>
                <TextInput
                    label="Repository URL"
                    autoComplete="off"
                    {...form.getInputProps('repo_url')}
                />
                <Group grow align="flex-start">
                    <TextInput label="Branch" {...form.getInputProps('branch')} />
                    <TextInput label="Subdirectory" {...form.getInputProps('subdir')} />
                </Group>
                <TextInput
                    label="Health check path"
                    placeholder="/healthz"
                    description={HEALTH_PATH_HELP}
                    autoComplete="off"
                    {...form.getInputProps('health_path')}
                />
                <Text size="xs" c="gray.6">
                    Changes apply on the next deploy.
                </Text>
                <Group justify="flex-end">
                    <Button variant="default" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button type="submit" loading={isLoading}>
                        Save
                    </Button>
                </Group>
            </Stack>
        </form>
    );
}
