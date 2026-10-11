'use client';

import { ActionIcon, Tooltip } from '@mantine/core';
import { useClipboard } from '@mantine/hooks';
import { IconCheck, IconCopy } from '@tabler/icons-react';
import { Mono } from './Mono';
import classes from './IdText.module.css';

interface IdTextProps {
    /** Full value: copied to the clipboard and shown as the tooltip. */
    value: string;
    /** Shorter text to render instead of the full value. */
    display?: string;
    chip?: boolean;
}

export function IdText({ value, display, chip }: IdTextProps) {
    const clipboard = useClipboard({ timeout: 1500 });

    return (
        <span className={classes.root}>
            <Mono className={chip ? classes.chip : classes.text} title={value}>
                {display ?? value}
            </Mono>
            <Tooltip label={clipboard.copied ? 'Copied' : 'Copy'} withArrow position="top">
                <ActionIcon
                    variant="subtle"
                    color="gray"
                    size="sm"
                    aria-label="Copy"
                    onClick={() => clipboard.copy(value)}
                >
                    {clipboard.copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
                </ActionIcon>
            </Tooltip>
        </span>
    );
}
