'use client';

import {
    ActionIcon,
    Alert,
    Button,
    Group,
    Modal,
    PasswordInput,
    ScrollArea,
    Stack,
    Text,
    TextInput,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { IconInfoCircle, IconPlus, IconTrash } from '@tabler/icons-react';
import { useState } from 'react';
import { useSetEnv } from '../hooks/useSetEnv';
import {
    ENV_MAX_KEYS,
    rowsFromKeys,
    rowsToEnv,
    validateEnvRows,
    type EnvRow,
} from '../services/env';
import type { BultApp } from '../types';

interface EnvModalProps {
    app: BultApp;
    opened: boolean;
    onClose: () => void;
}

export function EnvModal({ app, opened, onClose }: EnvModalProps) {
    return (
        <Modal
            opened={opened}
            onClose={onClose}
            title={`Variables of ${app.name}`}
            size="lg"
            centered
        >
            <EnvForm app={app} onClose={onClose} />
        </Modal>
    );
}

// Mounted only while the modal is open, so the rows always start from the current keys.
function EnvForm({ app, onClose }: { app: BultApp; onClose: () => void }) {
    const { submit, isLoading } = useSetEnv();
    const [serverError, setServerError] = useState<string>();
    const [nextId, setNextId] = useState(0);

    const form = useForm<{ rows: EnvRow[] }>({
        mode: 'controlled',
        initialValues: { rows: rowsFromKeys(app.env_keys) },
        validate: (values) => validateEnvRows(values.rows),
    });

    const addRow = () => {
        form.insertListItem('rows', { id: `new:${nextId}`, key: '', value: '', existing: false });
        setNextId(nextId + 1);
    };

    const handleSubmit = async ({ rows }: { rows: EnvRow[] }) => {
        setServerError(undefined);
        const result = await submit(app.name, rowsToEnv(rows));
        if (result.ok) onClose();
        else setServerError(result.envError);
    };

    return (
        <form onSubmit={form.onSubmit(handleSubmit)} noValidate>
            <Stack gap="md">
                <Alert color="sky" icon={<IconInfoCircle size={16} />}>
                    Values are write-only: they are never shown again. Saving replaces all
                    variables, so type the value again for every variable you keep, or remove it.
                </Alert>

                <ScrollArea.Autosize mah={360} type="auto">
                    <Stack gap="xs" pr="xs">
                        {form.values.rows.length === 0 && (
                            <Text size="sm" c="gray.6">
                                No variables.
                            </Text>
                        )}
                        {form.values.rows.map((row, i) => (
                            <Group key={row.id} align="flex-start" gap="xs" wrap="nowrap">
                                <TextInput
                                    aria-label="Name"
                                    placeholder="NAME"
                                    style={{ flex: 1 }}
                                    autoComplete="off"
                                    readOnly={row.existing}
                                    {...form.getInputProps(`rows.${i}.key`)}
                                    onChange={(e) =>
                                        form.setFieldValue(
                                            `rows.${i}.key`,
                                            e.currentTarget.value.toUpperCase(),
                                        )
                                    }
                                />
                                <PasswordInput
                                    aria-label={`Value of ${row.key || 'the new variable'}`}
                                    placeholder={row.existing ? 'type the value again' : 'value'}
                                    style={{ flex: 1 }}
                                    autoComplete="new-password"
                                    {...form.getInputProps(`rows.${i}.value`)}
                                />
                                <ActionIcon
                                    variant="subtle"
                                    color="red"
                                    size="lg"
                                    aria-label={`Remove ${row.key || 'variable'}`}
                                    onClick={() => form.removeListItem('rows', i)}
                                >
                                    <IconTrash size={16} />
                                </ActionIcon>
                            </Group>
                        ))}
                    </Stack>
                </ScrollArea.Autosize>

                {form.errors.rows && (
                    <Text size="sm" c="red">
                        {form.errors.rows}
                    </Text>
                )}
                {serverError && (
                    <Alert color="red" icon={<IconInfoCircle size={16} />}>
                        {serverError}
                    </Alert>
                )}

                <Group justify="space-between">
                    <Button
                        variant="default"
                        leftSection={<IconPlus size={16} />}
                        disabled={form.values.rows.length >= ENV_MAX_KEYS}
                        onClick={addRow}
                    >
                        Add variable
                    </Button>
                    <Group>
                        <Button variant="default" onClick={onClose}>
                            Cancel
                        </Button>
                        <Button type="submit" loading={isLoading}>
                            Save
                        </Button>
                    </Group>
                </Group>
                <Text size="xs" c="gray.6">
                    Changes apply on the next deploy.
                </Text>
            </Stack>
        </form>
    );
}
