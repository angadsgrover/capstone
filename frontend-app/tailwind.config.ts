import type { Config } from 'tailwindcss'

const config: Config = {
  darkMode: ['class'],
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // Material Design 3 Color System - Dark Theme
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',

        // Primary - Indigo/Purple theme
        primary: {
          DEFAULT: 'hsl(var(--primary))', // #c0c1ff
          foreground: 'hsl(var(--primary-foreground))',
          container: 'hsl(var(--primary-container))', // #8083ff
          fixed: 'hsl(var(--primary-fixed))',
          'fixed-dim': 'hsl(var(--primary-fixed-dim))',
        },

        // Secondary - Cyan theme
        secondary: {
          DEFAULT: 'hsl(var(--secondary))', // #5de6ff
          foreground: 'hsl(var(--secondary-foreground))',
          container: 'hsl(var(--secondary-container))', // #00cbe6
          fixed: 'hsl(var(--secondary-fixed))',
          'fixed-dim': 'hsl(var(--secondary-fixed-dim))',
        },

        // Tertiary - Purple/Blue theme
        tertiary: {
          DEFAULT: 'hsl(var(--tertiary))',
          foreground: 'hsl(var(--tertiary-foreground))',
          container: 'hsl(var(--tertiary-container))',
          fixed: 'hsl(var(--tertiary-fixed))',
          'fixed-dim': 'hsl(var(--tertiary-fixed-dim))',
        },

        // Error
        error: {
          DEFAULT: 'hsl(var(--error))',
          foreground: 'hsl(var(--error-foreground))',
          container: 'hsl(var(--error-container))',
        },

        // Surface variants
        surface: {
          DEFAULT: 'hsl(var(--surface))', // #0b1326
          dim: 'hsl(var(--surface-dim))',
          bright: 'hsl(var(--surface-bright))',
          variant: 'hsl(var(--surface-variant))',
          container: {
            DEFAULT: 'hsl(var(--surface-container))',
            lowest: 'hsl(var(--surface-container-lowest))',
            low: 'hsl(var(--surface-container-low))',
            high: 'hsl(var(--surface-container-high))',
            highest: 'hsl(var(--surface-container-highest))',
          },
          tint: 'hsl(var(--surface-tint))',
        },

        // On-surface colors
        'on-background': 'hsl(var(--on-background))',
        'on-surface': 'hsl(var(--on-surface))',
        'on-surface-variant': 'hsl(var(--on-surface-variant))',
        'on-primary': 'hsl(var(--on-primary))',
        'on-primary-container': 'hsl(var(--on-primary-container))',
        'on-secondary': 'hsl(var(--on-secondary))',
        'on-secondary-container': 'hsl(var(--on-secondary-container))',
        'on-tertiary': 'hsl(var(--on-tertiary))',
        'on-tertiary-container': 'hsl(var(--on-tertiary-container))',
        'on-error': 'hsl(var(--on-error))',
        'on-error-container': 'hsl(var(--on-error-container))',

        // Outline
        outline: {
          DEFAULT: 'hsl(var(--outline))',
          variant: 'hsl(var(--outline-variant))',
        },

        // Inverse
        'inverse-surface': 'hsl(var(--inverse-surface))',
        'inverse-on-surface': 'hsl(var(--inverse-on-surface))',
        'inverse-primary': 'hsl(var(--inverse-primary))',
      },
      borderRadius: {
        lg: '0.5rem',  // 8px - Material Design rounded
        md: '0.25rem', // 4px
        sm: '0.125rem', // 2px
        xl: '0.75rem', // 12px
        '2xl': '1rem', // 16px
        '3xl': '1.5rem', // 24px
      },
      fontFamily: {
        headline: ['Inter', 'sans-serif'],
        body: ['Inter', 'sans-serif'],
        label: ['Inter', 'sans-serif'],
      },
    },
  },
  plugins: [],
}

export default config
