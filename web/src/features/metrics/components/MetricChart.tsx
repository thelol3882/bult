'use client';

import { LineChart } from '@mantine/charts';
import { Card } from '@mantine/core';
import { REMOVED_SUFFIX, type ChartModel } from '../services/chart';
import classes from './MetricChart.module.css';

interface MetricChartProps {
    title: string;
    model: ChartModel;
    /** Formats a value for the tooltip and the legend. */
    format: (value: number) => string;
    /** A horizontal guide, e.g. 100 for "at the CPU limit". */
    guide?: { value: number; label: string };
}

/** One line per replica, a legend with the newest values, and a tooltip. */
export function MetricChart({ title, model, format, guide }: MetricChartProps) {
    return (
        <Card padding={0}>
            <div className={classes.head}>
                <h3>{title}</h3>
            </div>
            <div className={classes.plot}>
                <LineChart
                    h={240}
                    data={model.rows}
                    dataKey="time"
                    series={model.lines.map((line) => ({
                        name: line.name,
                        label: line.label,
                        color: line.color,
                        strokeDasharray: line.dashed ? '5 4' : undefined,
                    }))}
                    curveType="linear"
                    withDots={false}
                    strokeWidth={2}
                    gridAxis="y"
                    tickLine="none"
                    valueFormatter={format}
                    xAxisProps={{ minTickGap: 56 }}
                    yAxisProps={{ domain: [0, 'auto'], width: 64, tickFormatter: format }}
                    referenceLines={
                        guide
                            ? [{ y: guide.value, label: guide.label, color: 'var(--slate-5)' }]
                            : undefined
                    }
                />
            </div>
            <ul className={classes.legend}>
                {model.lines.map((line) => (
                    <li key={line.name} className={line.live ? undefined : classes.removed}>
                        <svg width="22" height="8" aria-hidden="true">
                            <line
                                x1="1"
                                x2="21"
                                y1="4"
                                y2="4"
                                stroke={line.color}
                                strokeWidth="2.5"
                                strokeLinecap="round"
                                strokeDasharray={line.dashed ? '5 4' : undefined}
                            />
                        </svg>
                        <span>
                            {line.live ? line.label : line.label.slice(0, -REMOVED_SUFFIX.length)}
                            {!line.live && <i className={classes.tag}>{REMOVED_SUFFIX}</i>}
                        </span>
                        <b>{line.last === null ? '-' : format(line.last)}</b>
                    </li>
                ))}
            </ul>
        </Card>
    );
}
