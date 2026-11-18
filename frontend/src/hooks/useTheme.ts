import { useCallback, useEffect, useState } from 'react'

export type ThemePreference = 'system' | 'light' | 'dark'
export type ResolvedTheme = 'light' | 'dark'

const STORAGE_KEY = 'url_shortener_theme'

// Read OS/browser color preference
export function getSystemTheme(): ResolvedTheme {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return 'light'
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function resolveTheme(pref: ThemePreference): ResolvedTheme {
  return pref === 'system' ? getSystemTheme() : pref
}

function getStoredPreference(): ThemePreference {
  if (typeof window === 'undefined') return 'system'
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    if (saved === 'light' || saved === 'dark' || saved === 'system') {
      return saved
    }
  } catch {
    // Storage unavailable, fall back to system
  }
  return 'system'
}

// Apply theme attributes to <html> immediately
export function applyThemeToDom(resolved: ResolvedTheme): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.setAttribute('data-theme', resolved)
  root.classList.toggle('dark', resolved === 'dark')
  root.style.colorScheme = resolved
}

// Apply initial theme before first React paint
export function initTheme(): void {
  applyThemeToDom(resolveTheme(getStoredPreference()))
}

export function useTheme() {
  const [preference, setPreferenceState] = useState<ThemePreference>(getStoredPreference)
  const [resolved, setResolved] = useState<ResolvedTheme>(() => resolveTheme(getStoredPreference()))

  const updateDom = useCallback((pref: ThemePreference) => {
    const next = resolveTheme(pref)
    setResolved(next)
    applyThemeToDom(next)
  }, [])

  useEffect(() => {
    updateDom(preference)

    // Listen for live OS theme changes when following system
    if (typeof window.matchMedia !== 'function') return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const onSystemChange = () => {
      if (preference === 'system') {
        updateDom('system')
      }
    }

    media.addEventListener('change', onSystemChange)
    return () => media.removeEventListener('change', onSystemChange)
  }, [preference, updateDom])

  const setPreference = useCallback(
    (next: ThemePreference) => {
      setPreferenceState(next)
      try {
        window.localStorage.setItem(STORAGE_KEY, next)
      } catch {
        // Ignore storage write errors
      }
      updateDom(next)
    },
    [updateDom]
  )

  // Cycle cleanly: system -> light -> dark -> system
  const cycleTheme = useCallback(() => {
    const order: ThemePreference[] = ['system', 'light', 'dark']
    const next = order[(order.indexOf(preference) + 1) % order.length]
    setPreference(next)
  }, [preference, setPreference])

  return { preference, resolved, setPreference, cycleTheme }
}
