/** Deploy status -> Mantine color name. Use with <Badge color={...}>. */
export const deployStatusColor = {
    building: 'sun',
    starting: 'sky',
    running: 'green',
    failed: 'red',
} as const;
