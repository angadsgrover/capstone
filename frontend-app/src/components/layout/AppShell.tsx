import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  alpha,
  AppBar,
  Box,
  Chip,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  PaletteMode,
  Stack,
  Toolbar,
  Tooltip,
  Typography,
  useMediaQuery,
  useTheme,
} from '@mui/material'
import MaterialIcon from '@/components/ui/MaterialIcon'

const NAV_ITEMS = [
  { label: 'Agent',          path: '/chat',     icon: 'chat_bubble',     short: '1' },
  { label: 'Logs',           path: '/logs',     icon: 'terminal',        short: '2' },
]

interface AppShellProps {
  children: React.ReactNode
  mode: PaletteMode
  onToggleMode: () => void
}

export default function AppShell({ children, mode, onToggleMode }: AppShellProps) {
  const theme = useTheme()
  const isCompactLayout = useMediaQuery(theme.breakpoints.down('lg'))
  const navigate  = useNavigate()
  const location  = useLocation()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false)
  const desktopDrawerWidth = sidebarCollapsed ? 84 : 288

  useEffect(() => {
    if (isCompactLayout) return
    const sidebarStored = localStorage.getItem('sidebarCollapsed')
    setSidebarCollapsed(sidebarStored === 'true')
  }, [isCompactLayout])

  useEffect(() => {
    if (isCompactLayout) return
    localStorage.setItem('sidebarCollapsed', String(sidebarCollapsed))
  }, [isCompactLayout, sidebarCollapsed])

  useEffect(() => {
    if (!isCompactLayout) return
    setMobileDrawerOpen(false)
  }, [isCompactLayout, location.pathname])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return
      const item = NAV_ITEMS.find((t) => t.short === e.key)
      if (item) { e.preventDefault(); navigate(item.path) }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [navigate])

  const currentPath = location.pathname === '/' ? '/chat' : location.pathname
  const toggleSidebar = useCallback(() => setSidebarCollapsed((c) => !c), [])
  const handleNavigate = useCallback((path: string) => {
    navigate(path)
    if (isCompactLayout) {
      setMobileDrawerOpen(false)
    }
  }, [isCompactLayout, navigate])

  const drawerContent = (
    <Stack spacing={1} sx={{ px: isCompactLayout ? 2 : (sidebarCollapsed ? 1 : 2), pt: 2.5, height: '100%' }}>
      <Stack
        direction="row"
        spacing={1.5}
        alignItems="center"
        sx={{ justifyContent: (!isCompactLayout && sidebarCollapsed) ? 'center' : 'flex-start', px: 1, minHeight: 52 }}
      >
        <Box
          sx={{
            height: 40,
            width: 40,
            borderRadius: 2.5,
            display: 'grid',
            placeItems: 'center',
            color: 'primary.contrastText',
            background: 'linear-gradient(135deg, #1d4ed8 0%, #0f766e 100%)',
            boxShadow: `0 8px 20px ${alpha(theme.palette.primary.main, 0.32)}`,
          }}
        >
          <MaterialIcon icon="flight_takeoff" filled />
        </Box>
        {(isCompactLayout || !sidebarCollapsed) && (
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="subtitle1" fontWeight={700} noWrap>
              PolyU Aviation
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ letterSpacing: 0.9 }}>
              Weather Intelligence
            </Typography>
          </Box>
        )}
      </Stack>

      <Divider sx={{ my: 1 }} />

      <List disablePadding sx={{ px: 0.5, flexGrow: 1 }}>
        {NAV_ITEMS.map((item) => {
          const active = currentPath === item.path

          return (
            <Tooltip
              key={item.path}
              title={!isCompactLayout && sidebarCollapsed ? `${item.label} (Cmd+${item.short})` : ''}
              placement="right"
            >
              <ListItemButton
                selected={active}
                onClick={() => handleNavigate(item.path)}
                sx={{
                  px: (!isCompactLayout && sidebarCollapsed) ? 1 : 1.25,
                  py: 1.1,
                  mb: 0.7,
                  justifyContent: (!isCompactLayout && sidebarCollapsed) ? 'center' : 'flex-start',
                  '&.Mui-selected': {
                    bgcolor: alpha(theme.palette.primary.main, 0.15),
                    color: 'primary.main',
                    '&:hover': {
                      bgcolor: alpha(theme.palette.primary.main, 0.2),
                    },
                  },
                }}
              >
                <ListItemIcon
                  sx={{
                    minWidth: (!isCompactLayout && sidebarCollapsed) ? 'unset' : 38,
                    color: active ? 'primary.main' : 'text.secondary',
                  }}
                >
                  <MaterialIcon icon={item.icon} filled={active} />
                </ListItemIcon>
                {(isCompactLayout || !sidebarCollapsed) && (
                  <>
                    <ListItemText
                      primary={item.label}
                      primaryTypographyProps={{ fontSize: 14, fontWeight: active ? 700 : 600 }}
                    />
                    {!isCompactLayout && <Chip label={`Cmd+${item.short}`} size="small" variant="outlined" />}
                  </>
                )}
              </ListItemButton>
            </Tooltip>
          )
        })}
      </List>

      <Divider sx={{ mt: 1, mb: 1.5 }} />

      <Stack spacing={1} sx={{ pb: 1.5 }}>
        <ListItemButton onClick={onToggleMode} sx={{ justifyContent: (!isCompactLayout && sidebarCollapsed) ? 'center' : 'flex-start' }}>
          <ListItemIcon sx={{ minWidth: (!isCompactLayout && sidebarCollapsed) ? 'unset' : 38 }}>
            <MaterialIcon icon={mode === 'dark' ? 'dark_mode' : 'light_mode'} />
          </ListItemIcon>
          {(isCompactLayout || !sidebarCollapsed) && (
            <ListItemText
              primary={mode === 'dark' ? 'Dark Mode' : 'Light Mode'}
              primaryTypographyProps={{ fontSize: 14, fontWeight: 600 }}
            />
          )}
        </ListItemButton>

        {!isCompactLayout && (
          <ListItemButton onClick={toggleSidebar} sx={{ justifyContent: sidebarCollapsed ? 'center' : 'flex-start' }}>
            <ListItemIcon sx={{ minWidth: sidebarCollapsed ? 'unset' : 38 }}>
              <MaterialIcon icon={sidebarCollapsed ? 'keyboard_double_arrow_right' : 'keyboard_double_arrow_left'} />
            </ListItemIcon>
            {!sidebarCollapsed && (
              <ListItemText primary="Collapse Sidebar" primaryTypographyProps={{ fontSize: 14, fontWeight: 600 }} />
            )}
          </ListItemButton>
        )}
      </Stack>
    </Stack>
  )

  return (
    <Box sx={{ display: 'flex', width: '100%', height: '100dvh', minHeight: '100svh', overflow: 'hidden' }}>
      {!isCompactLayout && (
        <Drawer
          variant="permanent"
          sx={{
            width: desktopDrawerWidth,
            flexShrink: 0,
            transition: theme.transitions.create('width', {
              duration: theme.transitions.duration.standard,
            }),
            '& .MuiDrawer-paper': {
              width: desktopDrawerWidth,
              borderRight: `1px solid ${alpha(theme.palette.divider, 0.7)}`,
              bgcolor: alpha(theme.palette.background.paper, 0.88),
              backdropFilter: 'blur(14px)',
              transition: theme.transitions.create('width', {
                duration: theme.transitions.duration.standard,
              }),
            },
          }}
        >
          {drawerContent}
        </Drawer>
      )}

      {isCompactLayout && (
        <Drawer
          variant="temporary"
          open={mobileDrawerOpen}
          onClose={() => setMobileDrawerOpen(false)}
          ModalProps={{ keepMounted: true }}
          sx={{
            '& .MuiDrawer-paper': {
              width: 290,
              borderRight: `1px solid ${alpha(theme.palette.divider, 0.7)}`,
              bgcolor: alpha(theme.palette.background.paper, 0.94),
              backdropFilter: 'blur(14px)',
            },
          }}
        >
          {drawerContent}
        </Drawer>
      )}

      <Box sx={{ minWidth: 0, flex: 1, display: 'flex', flexDirection: 'column' }}>
        <AppBar
          position="static"
          color="transparent"
          elevation={0}
          sx={{
            borderBottom: `1px solid ${alpha(theme.palette.divider, 0.6)}`,
            bgcolor: alpha(theme.palette.background.default, 0.7),
            backdropFilter: 'blur(10px)',
          }}
        >
          <Toolbar sx={{ px: { xs: 2, md: 3 }, gap: 1.5 }}>
            {isCompactLayout && (
              <IconButton color="inherit" edge="start" onClick={() => setMobileDrawerOpen(true)}>
                <MaterialIcon icon="menu" />
              </IconButton>
            )}
            <Typography variant="h6" noWrap sx={{ flexGrow: 1, fontSize: { xs: '1rem', md: '1.1rem' } }}>
              PolyU Aviation Weather Intelligence
            </Typography>
            <Chip color="secondary" size="small" icon={<span style={{ width: 8, height: 8, borderRadius: 999, background: 'currentColor' }} />} label="Live" />
            <Tooltip title="Toggle color mode">
              <IconButton color="inherit" onClick={onToggleMode}>
                <MaterialIcon icon={mode === 'dark' ? 'light_mode' : 'dark_mode'} />
              </IconButton>
            </Tooltip>
          </Toolbar>
        </AppBar>

        <Box sx={{ flex: 1, minHeight: 0, overflow: 'auto', pb: 'env(safe-area-inset-bottom)' }}>
          {children}
        </Box>
      </Box>
    </Box>
  )
}
