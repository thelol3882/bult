// bult Mantine 8 theme (draft v0.1). Mirrors tokens.css.
// Usage (app/layout.tsx):
//   <MantineProvider theme={bultTheme} defaultColorScheme="light">...</MantineProvider>
// Fonts are loaded with next/font/google (Bricolage_Grotesque, Onest, JetBrains_Mono)
// and exposed as CSS variables --font-display / --font-sans / --font-mono.
import {
  Badge,
  Button,
  Card,
  Code,
  createTheme,
  type MantineColorsTuple,
  Paper,
  Table,
  TextInput,
} from "@mantine/core";

// Index 5 = brand anchor (flag colors). Index 0 lightest, 9 darkest.
const sky: MantineColorsTuple = [
  "#e8f9fc", "#c7f0f7", "#97e3ef", "#5fd3e4", "#26c1d8",
  "#00afca", "#0094ad", "#00788d", "#005d6e", "#003f4c",
];

const sun: MantineColorsTuple = [
  "#fffae6", "#fff1bf", "#ffe58a", "#ffd950", "#fecd26",
  "#fec50c", "#e0a800", "#b08300", "#8a6500", "#5e4500",
];

// Replaces Mantine's "gray": cool neutral tinted toward the sky.
const slate: MantineColorsTuple = [
  "#f5f8fa", "#edf2f5", "#e2e8ee", "#cbd5dd", "#a3b1be",
  "#7a8b9b", "#5b6b7b", "#3f4e5c", "#26333f", "#0b1622",
];

// Replaces Mantine's "dark": night sky. Used for dark surfaces (log viewer).
const night: MantineColorsTuple = [
  "#c9d6e0", "#9fb3c4", "#6e879c", "#4a6378", "#2e4659",
  "#1d3447", "#132838", "#0e2030", "#0a1826", "#061220",
];

const green: MantineColorsTuple = [
  "#e7f6ef", "#c6ebda", "#98dcbe", "#64cba0", "#2fb07f",
  "#1f9a6c", "#158a60", "#0f7a55", "#0a5f42", "#05442f",
];

const red: MantineColorsTuple = [
  "#fff0f1", "#ffd9dd", "#ffb3bb", "#fb8794", "#f05f71",
  "#e5485b", "#d43448", "#c4283c", "#9e1d2f", "#721422",
];

/** Deploy status -> Mantine color name. Use with <Badge color={...}>. */
export const deployStatusColor = {
  building: "sun",
  starting: "sky",
  running: "green",
  failed: "red",
  stopped: "gray",
} as const;
export type DeployStatus = keyof typeof deployStatusColor;

export const bultTheme = createTheme({
  colors: { sky, sun, gray: slate, dark: night, green, red, yellow: sun },
  primaryColor: "sky",
  // Shade 7 keeps Anchor, Checkbox, Switch, active NavLink etc. at AA on white
  // (#00788D = 5.2:1). Filled buttons are re-mapped below to the real flag blue.
  primaryShade: { light: 7, dark: 4 },
  white: "#ffffff",
  black: "#0b1622",

  fontFamily: "var(--font-sans), Onest, system-ui, -apple-system, 'Segoe UI', sans-serif",
  fontFamilyMonospace: "var(--font-mono), 'JetBrains Mono', ui-monospace, Menlo, monospace",
  headings: {
    // Dashboard headings stay in the UI face; Bricolage is for the landing only.
    fontFamily: "var(--font-sans), Onest, system-ui, sans-serif",
    fontWeight: "600",
    sizes: {
      h1: { fontSize: "2rem", lineHeight: "1.2" },
      h2: { fontSize: "1.5rem", lineHeight: "1.25" },
      h3: { fontSize: "1.25rem", lineHeight: "1.3" },
      h4: { fontSize: "1rem", lineHeight: "1.4" },
      h5: { fontSize: "0.875rem", lineHeight: "1.4" },
      h6: { fontSize: "0.75rem", lineHeight: "1.4" },
    },
  },

  fontSizes: {
    xs: "0.75rem",
    sm: "0.8125rem",
    md: "0.875rem",
    lg: "1rem",
    xl: "1.25rem",
  },
  lineHeights: { xs: "1.4", sm: "1.45", md: "1.5", lg: "1.55", xl: "1.6" },

  radius: { xs: "4px", sm: "6px", md: "8px", lg: "12px", xl: "20px" },
  defaultRadius: "md",
  spacing: { xs: "8px", sm: "12px", md: "16px", lg: "24px", xl: "32px" },

  shadows: {
    xs: "0 1px 2px rgba(11, 22, 34, 0.06)",
    sm: "0 1px 2px rgba(11, 22, 34, 0.05), 0 2px 6px rgba(11, 22, 34, 0.05)",
    md: "0 2px 4px rgba(11, 22, 34, 0.04), 0 8px 24px rgba(11, 40, 60, 0.08)",
    lg: "0 4px 8px rgba(11, 22, 34, 0.04), 0 20px 48px rgba(11, 40, 60, 0.14)",
    xl: "0 24px 60px -12px rgba(0, 93, 110, 0.28)",
  },

  focusRing: "auto",
  cursorType: "pointer",
  respectReducedMotion: true,

  components: {
    Button: Button.extend({
      defaultProps: { radius: "md", fw: 500 },
      // Primary filled button = flag blue with navy label (6.9:1).
      // White on #00AFCA is only 2.6:1, so never put white text on it.
      vars: (_theme, props) => {
        const isPrimaryFilled =
          (props.variant === undefined || props.variant === "filled") &&
          (props.color === undefined || props.color === "sky");
        if (!isPrimaryFilled) return { root: {} };
        return {
          root: {
            "--button-bg": "var(--mantine-color-sky-5)",
            "--button-hover": "var(--mantine-color-sky-4)",
            "--button-color": "var(--mantine-color-gray-9)",
            "--button-bd": "1px solid var(--mantine-color-sky-6)",
          },
        };
      },
    }),

    Badge: Badge.extend({
      defaultProps: { variant: "light", radius: "sm", size: "md" },
      styles: {
        root: { textTransform: "none", letterSpacing: 0, fontWeight: 500 },
      },
    }),

    Card: Card.extend({
      defaultProps: { withBorder: true, radius: "lg", padding: "lg", shadow: "xs" },
    }),

    Paper: Paper.extend({
      defaultProps: { withBorder: true, radius: "lg", shadow: "xs" },
    }),

    TextInput: TextInput.extend({
      defaultProps: { radius: "md", size: "sm" },
      styles: {
        label: { fontWeight: 500, marginBottom: 6 },
        description: { color: "var(--mantine-color-gray-6)" },
        error: { fontSize: "var(--mantine-font-size-xs)" },
      },
    }),

    Table: Table.extend({
      defaultProps: {
        verticalSpacing: "sm",
        horizontalSpacing: "md",
        highlightOnHover: true,
        withRowBorders: true,
      },
      styles: {
        th: {
          fontSize: "var(--mantine-font-size-xs)",
          fontWeight: 500,
          color: "var(--mantine-color-gray-6)",
          background: "var(--mantine-color-gray-0)",
        },
        td: { fontSize: "var(--mantine-font-size-sm)" },
      },
    }),

    Code: Code.extend({
      styles: {
        root: {
          fontFamily: "var(--mantine-font-family-monospace)",
          fontSize: "0.8em",
          background: "var(--mantine-color-gray-1)",
          color: "var(--mantine-color-gray-8)",
          borderRadius: "var(--mantine-radius-xs)",
        },
      },
    }),
  },

  other: {
    fontDisplay: "var(--font-display), 'Bricolage Grotesque', Onest, sans-serif",
    logBackground: "#0a1826",
    flagBlue: "#00afca",
    flagGold: "#fec50c",
  },
});
