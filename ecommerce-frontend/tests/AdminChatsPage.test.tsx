import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth-store'
import { AdminChatsPage } from '@/pages/AdminChatsPage'
import type { ChatConversation, ChatMessage } from '@/types/models'

const { sendMessage } = vi.hoisted(() => ({
  sendMessage: vi.fn(() => true),
}))

vi.mock('@/hooks/use-web-socket', () => ({
  useWebSocket: () => ({ status: 'connected', send: sendMessage }),
}))

const conversation: ChatConversation = {
  customer_id: 12,
  customer_name: 'Taylor Customer',
  customer_email: 'taylor@example.com',
  last_message: 'Can you help with my order?',
  last_sender_id: 12,
  last_message_at: '2026-10-14T09:00:00Z',
}

const history: ChatMessage[] = [{
  id: 1,
  sender_id: 12,
  sender_name: 'Taylor Customer',
  recipient_id: 3,
  recipient_name: 'Store Admin',
  text: 'Can you help with my order?',
  created_at: '2026-10-14T09:00:00Z',
}]

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  sendMessage.mockClear()
  useAuthStore.setState({ token: null, user: null, loading: false })
})

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <AdminChatsPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('AdminChatsPage', () => {
  it('loads saved customer conversations and sends replies through live support', async () => {
    useAuthStore.setState({
      token: 'admin-token',
      user: { id: 3, name: 'Store Admin', email: 'admin@example.com', role: 'admin' },
      loading: false,
    })
    const get = vi.spyOn(api, 'get').mockImplementation(async (url) => ({
      data: {
        success: true,
        message: 'ok',
        data: url === '/chats/conversations' ? [conversation] : history,
      },
    }) as never)

    renderPage()

    expect((await screen.findAllByText('Taylor Customer')).length).toBeGreaterThan(0)
    expect(await screen.findByText('Can you help with my order?')).toBeInTheDocument()
    await waitFor(() => expect(get).toHaveBeenCalledWith('/chats/', { params: { customer_id: 12 } }))

    fireEvent.change(screen.getByRole('textbox', { name: 'Message customer' }), {
      target: { value: 'Your order is on its way.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    expect(sendMessage).toHaveBeenCalledWith({
      type: 'chat.send',
      data: { recipient_id: 12, text: 'Your order is on its way.' },
    })
  })
})
