import { Monitor, Moon, Sun } from 'lucide-react'
import { useTheme } from '../hooks/useTheme'

interface ThemeToggleProps {
  variant?: 'glass' | 'ds'
}

// Compact theme switcher cycling Auto (OS default) -> Light -> Dark
export function ThemeToggle({ variant = 'glass' }: ThemeToggleProps) {
  const { preference, resolved, cycleTheme } = useTheme()

  const label =
    preference === 'system'
      ? `Auto (${resolved === 'dark' ? 'Dark' : 'Light'})`
      : preference === 'dark'
        ? 'Dark'
        : 'Light'

  const Icon = preference === 'system' ? Monitor : resolved === 'dark' ? Moon : Sun

  if (variant === 'ds') {
    return (
      <button
        type="button"
        onClick={cycleTheme}
        className="ds-btn-secondary"
        title="Switch color theme (Auto / Light / Dark)"
        aria-label={`Theme: ${label}`}
      >
        <Icon className="h-4 w-4" />
        <span>{label}</span>
      </button>
    )
  }

  return (
    <button
      type="button"
      onClick={cycleTheme}
      className="liquid-theme-btn inline-flex h-8 items-center gap-2 px-3 text-xs font-medium"
      title="Switch color theme (Auto / Light / Dark)"
      aria-label={`Theme: ${label}`}
    >
      <Icon className="h-4 w-4 shrink-0" strokeWidth={1.5} />
      <span>{label}</span>
    </button>
  )
}
