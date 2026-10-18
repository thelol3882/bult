'use client';

import { useState } from 'react';
import { ActionIcon, Button, Card, Text, Tooltip } from '@mantine/core';
import { modals } from '@mantine/modals';
import { IconMinus, IconPlus, IconStack2 } from '@tabler/icons-react';
import { MAX_REPLICAS, stepReplicas } from '../services/replicas';
import classes from './ReplicasCard.module.css';

interface ReplicasCardProps {
    name: string;
    /** Desired replicas of the app now. */
    replicas: number;
    /** Why the count cannot be changed now; the controls are disabled with this as the hint. */
    blockedReason?: string;
    isScaling: boolean;
    /** Applies the new count; the card asks for confirmation before going to 0. */
    onApply: (replicas: number) => void;
}

/** A 0..5 stepper: pick a count, then apply it (same image, no build). */
export function ReplicasCard({
    name,
    replicas,
    blockedReason,
    isScaling,
    onApply,
}: ReplicasCardProps) {
    // The pick only counts while the app still has the count it was made against.
    const [pick, setPick] = useState<{ from: number; value: number } | null>(null);
    const value = pick !== null && pick.from === replicas ? pick.value : replicas;
    const changed = value !== replicas;
    const blocked = blockedReason !== undefined;

    const step = (delta: 1 | -1) => setPick({ from: replicas, value: stepReplicas(value, delta) });

    const apply = () => {
        if (value !== 0) return onApply(value);
        modals.openConfirmModal({
            title: 'Stop app',
            centered: true,
            children: (
                <Text size="sm">
                    Set <b>{name}</b> to 0 replicas? It stops, and its URL shows a
                    &quot;stopped&quot; page until you scale it up again. The last image is kept, so
                    nothing is rebuilt.
                </Text>
            ),
            labels: { confirm: 'Stop', cancel: 'Cancel' },
            confirmProps: { color: 'red' },
            onConfirm: () => onApply(0),
        });
    };

    return (
        <Card padding={0}>
            <div className={classes.head}>
                <IconStack2 size={18} color="var(--sky-7)" />
                <h3>Replicas</h3>
            </div>
            <Tooltip label={blockedReason} disabled={!blocked} multiline maw={260}>
                <div className={classes.body}>
                    <ActionIcon
                        variant="default"
                        aria-label="Fewer replicas"
                        disabled={blocked || isScaling || value <= 0}
                        onClick={() => step(-1)}
                    >
                        <IconMinus size={16} />
                    </ActionIcon>
                    <span className={classes.value} aria-live="polite">
                        {value}
                    </span>
                    <ActionIcon
                        variant="default"
                        aria-label="More replicas"
                        disabled={blocked || isScaling || value >= MAX_REPLICAS}
                        onClick={() => step(1)}
                    >
                        <IconPlus size={16} />
                    </ActionIcon>
                    <Button
                        ml="auto"
                        loading={isScaling}
                        disabled={blocked || !changed}
                        color={value === 0 ? 'red' : undefined}
                        onClick={apply}
                    >
                        {value === 0 ? 'Stop' : 'Apply'}
                    </Button>
                </div>
            </Tooltip>
            <p className={classes.note}>
                0 to {MAX_REPLICAS}. The same image runs on more nodes behind one address; no build.
            </p>
        </Card>
    );
}
