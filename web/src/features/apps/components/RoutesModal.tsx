'use client';

import {
    ActionIcon,
    Alert,
    Button,
    Group,
    Modal,
    Select,
    Stack,
    Text,
    TextInput,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { IconInfoCircle, IconPlus, IconTrash } from '@tabler/icons-react';
import { useState } from 'react';
import { useGetAppsQuery } from '../api/appsApi';
import { useSetRoutes } from '../hooks/useSetRoutes';
import {
    MAX_ROUTES,
    rowsFromRoutes,
    rowsToRoutes,
    validateRouteRows,
    type RouteRow,
} from '../services/routes';
import type { BultApp } from '../types';

interface RoutesModalProps {
    app: BultApp;
    opened: boolean;
    onClose: () => void;
}

export function RoutesModal({ app, opened, onClose }: RoutesModalProps) {
    return (
        <Modal opened={opened} onClose={onClose} title={`Routes of ${app.name}`} size="lg" centered>
            <RoutesForm app={app} onClose={onClose} />
        </Modal>
    );
}

// Mounted only while the modal is open, so the rows always start from the current routes.
function RoutesForm({ app, onClose }: { app: BultApp; onClose: () => void }) {
    const { submit, isLoading } = useSetRoutes();
    const { data: apps, isLoading: appsLoading } = useGetAppsQuery(1);
    const [serverError, setServerError] = useState<string>();
    const [nextId, setNextId] = useState(0);

    const form = useForm<{ rows: RouteRow[] }>({
        mode: 'controlled',
        initialValues: { rows: rowsFromRoutes(app.routes) },
        validate: (values) => validateRouteRows(values.rows),
    });

    // The user's other apps (first page of the list); a route to the app itself is refused.
    const targets = (apps?.results ?? []).filter((a) => a.name !== app.name).map((a) => a.name);
    // Keep an existing target selectable even if it is not on the first page.
    const options = [
        ...new Set([...targets, ...form.values.rows.map((r) => r.app).filter(Boolean)]),
    ];

    const addRow = () => {
        form.insertListItem('rows', { id: `new:${nextId}`, path: '', app: '' });
        setNextId(nextId + 1);
    };

    const handleSubmit = async ({ rows }: { rows: RouteRow[] }) => {
        setServerError(undefined);
        const result = await submit(app.name, rowsToRoutes(rows));
        if (result.ok) onClose();
        else setServerError(result.routesError);
    };

    return (
        <form onSubmit={form.onSubmit(handleSubmit)} noValidate>
            <Stack gap="md">
                <Alert color="sky" icon={<IconInfoCircle size={16} />}>
                    A request to <b>{app.name}</b> under the path goes to the chosen app, with the
                    path unchanged (<code>/api/todos</code> stays <code>/api/todos</code>). Both
                    apps must be yours. Everything else is served by <b>{app.name}</b>.
                </Alert>

                <Stack gap="xs">
                    {form.values.rows.length === 0 && (
                        <Text size="sm" c="gray.6">
                            No routes.
                        </Text>
                    )}
                    {form.values.rows.map((row, i) => (
                        <Group key={row.id} align="flex-start" gap="xs" wrap="nowrap">
                            <TextInput
                                aria-label="Path"
                                placeholder="/api"
                                style={{ flex: 1 }}
                                autoComplete="off"
                                {...form.getInputProps(`rows.${i}.path`)}
                            />
                            <Select
                                aria-label="Target app"
                                placeholder={appsLoading ? 'Loading apps…' : 'Target app'}
                                style={{ flex: 1 }}
                                data={options}
                                searchable
                                nothingFoundMessage="No other apps"
                                {...form.getInputProps(`rows.${i}.app`)}
                                value={row.app || null}
                                onChange={(value) =>
                                    form.setFieldValue(`rows.${i}.app`, value ?? '')
                                }
                            />
                            <ActionIcon
                                variant="subtle"
                                color="red"
                                size="lg"
                                aria-label={`Remove route ${row.path || ''}`}
                                onClick={() => form.removeListItem('rows', i)}
                            >
                                <IconTrash size={16} />
                            </ActionIcon>
                        </Group>
                    ))}
                </Stack>

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
                        disabled={form.values.rows.length >= MAX_ROUTES}
                        onClick={addRow}
                    >
                        Add route
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
            </Stack>
        </form>
    );
}
