import { createTheme, responsiveFontSizes } from '@mui/material/styles'
import { PaletteMode } from '@mui/material'

export function buildAppTheme(mode: PaletteMode) {
  const isDark = mode === 'dark'

  const theme = createTheme({
    palette: {
      mode,
      primary: {
        main: isDark ? '#8ab4ff' : '#1d4ed8',
        light: isDark ? '#aecbff' : '#60a5fa',
        dark: isDark ? '#5f96f5' : '#1e3a8a',
      },
      secondary: {
        main: isDark ? '#35d4b9' : '#0f766e',
        light: isDark ? '#79ead8' : '#14b8a6',
        dark: isDark ? '#0ea58d' : '#115e59',
      },
      background: {
        default: isDark ? '#08101f' : '#eef3fb',
        paper: isDark ? '#101b2f' : '#ffffff',
      },
      success: {
        main: '#2e7d32',
      },
      warning: {
        main: '#ed6c02',
      },
      error: {
        main: '#d32f2f',
      },
    },
    shape: {
      borderRadius: 14,
    },
    typography: {
      fontFamily: [
        'Inter',
        'ui-sans-serif',
        'system-ui',
        '-apple-system',
        'Segoe UI',
        'sans-serif',
      ].join(','),
      h5: {
        fontWeight: 700,
        letterSpacing: '-0.01em',
      },
      h6: {
        fontWeight: 700,
      },
      button: {
        textTransform: 'none',
        fontWeight: 600,
      },
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          body: {
            backgroundImage: isDark
              ? 'radial-gradient(circle at 20% -10%, rgba(138, 180, 255, 0.20), transparent 50%), radial-gradient(circle at 95% 10%, rgba(53, 212, 185, 0.16), transparent 35%)'
              : 'radial-gradient(circle at 15% -20%, rgba(96, 165, 250, 0.20), transparent 45%), radial-gradient(circle at 95% 15%, rgba(20, 184, 166, 0.18), transparent 40%)',
            backgroundAttachment: 'fixed',
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: 'none',
          },
          rounded: {
            borderRadius: 16,
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 18,
          },
        },
      },
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 12,
            paddingInline: 14,
            minHeight: 40,
          },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: {
            borderRadius: 10,
            fontWeight: 600,
          },
        },
      },
      MuiOutlinedInput: {
        styleOverrides: {
          root: {
            borderRadius: 14,
          },
        },
      },
      MuiListItemButton: {
        styleOverrides: {
          root: {
            borderRadius: 12,
          },
        },
      },
    },
  })

  return responsiveFontSizes(theme)
}
