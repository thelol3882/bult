import { Badge, Table } from '@mantine/core';
import { Mono } from '@/shared/components';
import { formatMemory, lastSeenLabel, NODE_STATUS, roleLabel } from '../services/format';
import type { PlatformNode } from '../types';
import classes from './NodesTable.module.css';

export function NodesTable({ nodes }: { nodes: PlatformNode[] }) {
    return (
        <div className={classes.card}>
            <Table>
                <Table.Thead>
                    <Table.Tr>
                        <Table.Th>Node</Table.Th>
                        <Table.Th>Role</Table.Th>
                        <Table.Th>Status</Table.Th>
                        <Table.Th>Last seen</Table.Th>
                        <Table.Th ta="right">Replicas</Table.Th>
                        <Table.Th>Capacity</Table.Th>
                    </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                    {nodes.map((node) => (
                        <Table.Tr key={node.name}>
                            <Table.Td>
                                <span className={classes.name}>{node.name}</span>
                                {node.version && (
                                    <>
                                        {' '}
                                        <Mono className={classes.muted}>{node.version}</Mono>
                                    </>
                                )}
                            </Table.Td>
                            <Table.Td>{roleLabel(node.role)}</Table.Td>
                            <Table.Td>
                                <Badge color={NODE_STATUS[node.status].color}>
                                    {NODE_STATUS[node.status].label}
                                </Badge>
                            </Table.Td>
                            <Table.Td>{lastSeenLabel(node.last_seen_at)}</Table.Td>
                            <Table.Td ta="right">
                                <Mono>{node.replicas}</Mono>
                            </Table.Td>
                            <Table.Td>
                                <span className={classes.muted}>
                                    {node.cpus > 0 ? `${node.cpus} CPU` : '-'} ·{' '}
                                    {formatMemory(node.memory_bytes)}
                                </span>
                            </Table.Td>
                        </Table.Tr>
                    ))}
                </Table.Tbody>
            </Table>
        </div>
    );
}
