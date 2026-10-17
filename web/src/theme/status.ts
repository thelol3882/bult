/** Deploy status -> Mantine color name. Use with <Badge color={...}>. */
export const deployStatusColor = {
    queued: 'gray',
    building: 'sun',
    starting: 'sky',
    running: 'green',
    failed: 'red',
    cancelled: 'gray',
    superseded: 'gray',
    stopped: 'orange',
} as const;
