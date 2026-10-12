import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppErrorBoundary } from '@/components/AppErrorBoundary'

afterEach(() => vi.restoreAllMocks())

describe('application error boundary', () => {
  it('shows a reload recovery state when a child fails during rendering', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    function BrokenPage(): ReactNode {
      throw new Error('Rendering failed')
    }

    render(<AppErrorBoundary><BrokenPage /></AppErrorBoundary>)

    expect(screen.getByRole('alert')).toHaveTextContent('This page could not be displayed.')
    expect(screen.getByRole('button', { name: 'Reload application' })).toBeInTheDocument()
  })
})
