'use client';

import { Button, Card } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { IconPencil } from '@tabler/icons-react';
import { Mono } from '@/shared/components';
import type { BultApp } from '../types';
import { EnvModal } from './EnvModal';
import classes from './EnvCard.module.css';

/** Environment variables of an app: the names only, the API never returns the values. */
export function EnvCard({ app }: { app: BultApp }) {
    const [opened, handlers] = useDisclosure(false);

    return (
        <Card padding={0}>
            <div className={classes.head}>
                <h3>Environment</h3>
                <Button
                    variant="default"
                    size="compact-sm"
                    leftSection={<IconPencil size={14} />}
                    onClick={handlers.open}
                >
                    Edit
                </Button>
            </div>
            {app.env_keys.length === 0 ? (
                <p className={classes.empty}>No variables.</p>
            ) : (
                <ul className={classes.keys}>
                    {app.env_keys.map((key) => (
                        <li key={key}>
                            <Mono>{key}</Mono>
                            <span className={classes.hidden}>••••••••</span>
                        </li>
                    ))}
                </ul>
            )}
            <p className={classes.note}>Values are write-only. Changes apply on the next deploy.</p>
            <EnvModal app={app} opened={opened} onClose={handlers.close} />
        </Card>
    );
}
