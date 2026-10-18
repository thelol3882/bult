import type { Metadata } from 'next';
import { NodesWidget } from '@/widgets/nodes';

export const metadata: Metadata = { title: 'Nodes' };

export default function NodesPage() {
    return <NodesWidget />;
}
