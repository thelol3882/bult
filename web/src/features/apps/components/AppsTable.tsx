'use client';

import Link from 'next/link';
import { ActionIcon, Menu, Table } from '@mantine/core';
import { IconCloudUpload, IconDots, IconExternalLink, IconTrash } from '@tabler/icons-react';
import { Mono } from '@/shared/components';
import { fromNow } from '@/shared/utils/date';
import type { BultApp } from '../types';
import classes from './AppsTable.module.css';

interface AppsTableProps {
    apps: BultApp[];
    onDeploy: (name: string) => void;
    onDelete: (name: string) => void;
}

export function AppsTable({ apps, onDeploy, onDelete }: AppsTableProps) {
    return (
        <div className={classes.card}>
            <Table>
                <Table.Thead>
                    <Table.Tr>
                        <Table.Th w="28%">App</Table.Th>
                        <Table.Th>URL</Table.Th>
                        <Table.Th>Preset</Table.Th>
                        <Table.Th>Created</Table.Th>
                        <Table.Th w={48} />
                    </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                    {apps.map((app) => (
                        <Table.Tr key={app.name}>
                            <Table.Td>
                                <div className={classes.name}>
                                    <span className={classes.icon}>{app.name[0]}</span>
                                    <div>
                                        <Link href={`/apps/${app.name}`} className={classes.title}>
                                            {app.name}
                                        </Link>
                                        <small className={classes.meta}>
                                            {repoLabel(app.repo_url)} · {app.branch}
                                        </small>
                                    </div>
                                </div>
                            </Table.Td>
                            <Table.Td>
                                <a
                                    className={classes.link}
                                    href={app.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                >
                                    <Mono>{app.url.replace('https://', '')}</Mono>
                                    <IconExternalLink size={13} />
                                </a>
                            </Table.Td>
                            <Table.Td>
                                <Mono>{app.preset}</Mono>
                            </Table.Td>
                            <Table.Td c="gray.6">{fromNow(app.created_at)}</Table.Td>
                            <Table.Td>
                                <Menu position="bottom-end" withinPortal>
                                    <Menu.Target>
                                        <ActionIcon
                                            variant="subtle"
                                            color="gray"
                                            aria-label={`Actions for ${app.name}`}
                                        >
                                            <IconDots size={18} />
                                        </ActionIcon>
                                    </Menu.Target>
                                    <Menu.Dropdown>
                                        <Menu.Item
                                            leftSection={<IconCloudUpload size={16} />}
                                            onClick={() => onDeploy(app.name)}
                                        >
                                            Deploy
                                        </Menu.Item>
                                        <Menu.Item
                                            color="red"
                                            leftSection={<IconTrash size={16} />}
                                            onClick={() => onDelete(app.name)}
                                        >
                                            Delete
                                        </Menu.Item>
                                    </Menu.Dropdown>
                                </Menu>
                            </Table.Td>
                        </Table.Tr>
                    ))}
                </Table.Tbody>
            </Table>
        </div>
    );
}

function repoLabel(repoUrl: string): string {
    try {
        return new URL(repoUrl).pathname.replace(/^\/|\.git$/g, '');
    } catch {
        return repoUrl;
    }
}
