import type { Metadata } from 'next';
import { AppDetailWidget } from '@/widgets/app-detail';

type Props = { params: Promise<{ name: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
    const { name } = await params;
    return { title: name };
}

export default async function AppDetailPage({ params }: Props) {
    const { name } = await params;
    return <AppDetailWidget name={name} />;
}
