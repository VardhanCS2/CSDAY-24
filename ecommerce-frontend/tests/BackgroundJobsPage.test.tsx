import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import { BackgroundJobsPage } from '@/pages/BackgroundJobsPage'

const { authState } = vi.hoisted(() => ({
  authState: { user: null as null | { id: number; name: string; email: string; role: string } },
}))

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: authState.user }),
}))

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  authState.user = null
})

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <BackgroundJobsPage />
    </QueryClientProvider>,
  )
}

describe('BackgroundJobsPage AI usage dashboard', () => {
  it('shows provider quotas and feature usage for admins', async () => {
    authState.user = { id: 1, name: 'Admin', email: 'admin@example.com', role: 'admin' }
    vi.spyOn(api, 'get').mockImplementation(async (url) => ({
      data: {
        success: true,
        message: 'ok',
        data: url === '/jobs/' ? [] : {
          date_utc: '2026-10-13',
          providers: [{
            provider: 'groq',
            requests: 12,
            daily_limit: 500,
            feature_requests: { chat_stream: 8, product_content: 4 },
          }, {
            provider: 'mistral',
            requests: 7,
            daily_limit: null,
            feature_requests: { embedding: 7 },
          }],
        },
      },
    }) as never)

    renderPage()

    expect(await screen.findByRole('heading', { name: 'AI & Cost Governance' })).toBeInTheDocument()
    expect(await screen.findByText('12')).toBeInTheDocument()
    expect(screen.getByText('of 500')).toBeInTheDocument()
    expect(screen.getByText('488 requests remaining')).toBeInTheDocument()
    expect(screen.getByText('chat stream')).toBeInTheDocument()
    expect(screen.queryByText('mistral')).not.toBeInTheDocument()
    expect(screen.queryByText('embedding')).not.toBeInTheDocument()
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/ai/admin/usage')
    })
  })

  it('does not request or display AI usage for non-admin users', async () => {
    authState.user = { id: 2, name: 'Customer', email: 'user@example.com', role: 'customer' }
    const get = vi.spyOn(api, 'get').mockResolvedValue({
      data: { success: true, message: 'ok', data: [] },
    } as never)

    renderPage()

    await waitFor(() => expect(get).toHaveBeenCalledWith('/jobs/'))
    expect(screen.queryByRole('heading', { name: 'AI & Cost Governance' })).not.toBeInTheDocument()
    expect(get).not.toHaveBeenCalledWith('/ai/admin/usage')
  })
})
