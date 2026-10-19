'use client';

import { Button, Card } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { IconArrowRight, IconPencil } from '@tabler/icons-react';
import { Mono } from '@/shared/components';
import type { BultApp } from '../types';
import { RoutesModal } from './RoutesModal';
import classes from './RoutesCard.module.css';

/** Paths of the app's domain that other apps of the same owner serve (e.g. /api -> a backend). */
export function RoutesCard({ app }: { app: BultApp }) {
    const [opened, handlers] = useDisclosure(false);

    return (
        <Card padding={0}>
            <div className={classes.head}>
                <h3>Routes</h3>
                <Button
                    variant="default"
                    size="compact-sm"
                    leftSection={<IconPencil size={14} />}
                    onClick={handlers.open}
                >
                    Edit
                </Button>
            </div>
            {app.routes.length === 0 ? (
                <p className={classes.empty}>All paths go to this app.</p>
            ) : (
                <ul className={classes.list}>
                    {app.routes.map((route) => (
                        <li key={route.path}>
                            <Mono>{route.path}</Mono>
                            <IconArrowRight size={14} className={classes.arrow} />
                            <Mono>{route.app}</Mono>
                        </li>
                    ))}
                </ul>
            )}
            <p className={classes.note}>
                The path is passed on unchanged. Changes apply at once, without a deploy.
            </p>
            <RoutesModal app={app} opened={opened} onClose={handlers.close} />
        </Card>
    );
}
