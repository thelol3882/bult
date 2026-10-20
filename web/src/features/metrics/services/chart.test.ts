import { describe, expect, it } from 'vitest';
import type { AppMetrics, MetricsSeries } from '../types';
import {
    buildChart,
    formatBytes,
    formatCores,
    formatPercent,
    olderReplicaIds,
    replicaLabel,
} from './chart';

const T = Date.parse('2026-10-20T12:00:00Z');
const iso = (offset: number) => new Date(T + offset * 1000).toISOString();

function series(
    id: string,
    index: number,
    node: string,
    points: [number, number, number][],
    live = true,
) {
    return {
        replica_id: id,
        index,
        node,
        live,
        points: points.map(([o, cpu, mem]) => [iso(o), cpu, mem]),
    } as MetricsSeries;
}

function metrics(s: MetricsSeries[], width = 5): AppMetrics {
    return {
        period: '15m',
        bucket_seconds: width,
        series: s,
        summary: {
            cpu_cores: 0,
            mem_bytes: 0,
            mem_limit_bytes: 0,
            ready_replicas: 0,
            desired_replicas: 0,
        },
    };
}

describe('buildChart', () => {
    it('puts every replica on one regular time grid and leaves gaps as null', () => {
        const model = buildChart(
            metrics([
                series('d1-r0', 0, 'node-a', [
                    [0, 10, 100],
                    [5, 20, 200],
                    [15, 40, 400],
                ]),
                series('d1-r1', 1, 'node-b', [[10, 70, 700]]),
            ]),
            'cpu',
        );

        expect(model.rows).toHaveLength(4);
        expect(model.rows.map((r) => r['d1-r0'])).toEqual([10, 20, null, 40]);
        expect(model.rows.map((r) => r['d1-r1'])).toEqual([null, null, 70, null]);
    });

    it('reads memory from the third value of a point', () => {
        const model = buildChart(metrics([series('d1-r0', 0, 'node-a', [[0, 10, 111]])]), 'mem');

        expect(model.rows[0]['d1-r0']).toBe(111);
        expect(model.lines[0].last).toBe(111);
    });

    it('has no rows and no lines without data', () => {
        expect(buildChart(metrics([]), 'cpu')).toEqual({ rows: [], lines: [] });
    });

    it('labels lines as "r0 · node-1" and colours them by replica index', () => {
        const model = buildChart(
            metrics([
                series('d1-r0', 0, 'node-1', [[0, 1, 1]]),
                series('d1-r1', 1, 'node-2', [[0, 1, 1]]),
            ]),
            'cpu',
        );

        expect(model.lines.map((l) => l.label)).toEqual(['r0 · node-1', 'r1 · node-2']);
        expect(model.lines[0].color).not.toBe(model.lines[1].color);
        expect(model.lines.every((l) => !l.dashed)).toBe(true);
    });
});

describe('older deploys of the same replica index', () => {
    const old = series('aaaaaa111-r0', 0, 'node-1', [[0, 5, 5]]);
    const fresh = series('bbbbbb222-r0', 0, 'node-1', [
        [0, 5, 5],
        [10, 6, 6],
    ]);

    it('marks the series that ended earlier, and only it', () => {
        expect(olderReplicaIds([old, fresh])).toEqual(new Set(['aaaaaa111-r0']));
    });

    it('tells the two apart by label, keeps the colour, and draws the old one dashed', () => {
        const model = buildChart(metrics([old, fresh]), 'cpu');
        const [a, b] = model.lines;

        expect(a.label).toBe('r0 · node-1 · aaaaaa');
        expect(b.label).toBe('r0 · node-1');
        expect(a.color).toBe(b.color);
        expect([a.dashed, b.dashed]).toEqual([true, false]);
        expect(replicaLabel(fresh, false)).toBe('r0 · node-1');
    });
});

describe('removed replicas', () => {
    const gone = series('aaaaaa111-r0', 0, 'node-1', [[0, 5, 5]], false);
    const running = series('bbbbbb222-r1', 1, 'node-2', [[0, 6, 6]]);

    it('are dashed, muted, suffixed and listed after the live ones', () => {
        const model = buildChart(metrics([gone, running]), 'cpu');
        const [first, second] = model.lines;

        expect([first.name, second.name]).toEqual(['bbbbbb222-r1', 'aaaaaa111-r0']);
        expect([first.live, second.live]).toEqual([true, false]);
        expect([first.dashed, second.dashed]).toEqual([false, true]);
        expect(second.label).toBe('r0 · node-1 · removed');
        expect(second.color).toContain('color-mix');
        expect(first.color).toBe('var(--series-2)');
    });

    it('keep their history on the grid', () => {
        const model = buildChart(metrics([gone, running]), 'cpu');

        expect(model.rows.map((r) => r['aaaaaa111-r0'])).toEqual([5]);
    });

    it('stay dashed once, when they are also an older deploy', () => {
        const fresh = series('cccccc333-r0', 0, 'node-1', [[10, 1, 1]]);
        const model = buildChart(metrics([gone, fresh]), 'cpu');
        const removed = model.lines.find((l) => l.name === 'aaaaaa111-r0');

        expect(removed?.dashed).toBe(true);
        expect(removed?.label).toBe('r0 · node-1 · aaaaaa · removed');
    });
});

describe('formatters', () => {
    it('formats bytes in binary units', () => {
        expect(formatBytes(512)).toBe('512 B');
        expect(formatBytes(2048)).toBe('2 KiB');
        expect(formatBytes(5.5 * 1024 ** 2)).toBe('5.5 MiB');
        expect(formatBytes(150 * 1024 ** 2)).toBe('150 MiB');
        expect(formatBytes(2 * 1024 ** 3)).toBe('2.00 GiB');
    });

    it('formats percentages and cores', () => {
        expect(formatPercent(12.34)).toBe('12.3%');
        expect(formatPercent(250.4)).toBe('250%');
        expect(formatCores(0.256)).toBe('0.256');
        expect(formatCores(1.5)).toBe('1.50');
    });
});
