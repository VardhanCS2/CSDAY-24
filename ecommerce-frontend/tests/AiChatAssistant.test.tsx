import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { AiChatAssistant } from '@/components/AiChatAssistant'

afterEach(() => vi.unstubAllGlobals())

describe('AI shopping assistant', () => {
  it('opens as a separate guest-facing assistant from live support', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><AiChatAssistant /></MemoryRouter>)

    await user.click(screen.getByRole('button', { name: 'Open AI shopping assistant' }))

    expect(screen.getByRole('dialog', { name: 'AI shopping assistant' })).toBeInTheDocument()
    expect(screen.getByText(/For human help, use Live support in the top bar/)).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Ask about products' })).toBeInTheDocument()
    const closeButtons = screen.getAllByRole('button', { name: 'Close AI shopping assistant' })
    expect(closeButtons).toHaveLength(2)
    expect(closeButtons[1]).toHaveAttribute('aria-expanded', 'true')
  })

  it('renders streamed assistant text with clickable catalogue citations', async () => {
    const user = userEvent.setup()
    const events = [
      'data: {"type":"sources","label":"Same-category options over budget","sources":[{"product_id":12,"name":"Reusable glass bottle","price":24.5,"stock":8}]}\n\n',
      'data: {"type":"token","text":"This bottle is "}\n\n',
      'data: {"type":"token","text":"in stock [Product ID: 12]."}\n\n',
      'data: {"type":"done"}\n\n',
    ]
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: new ReadableStream({
        start(controller) {
          for (const event of events) controller.enqueue(new TextEncoder().encode(event))
          controller.close()
        },
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<MemoryRouter><AiChatAssistant /></MemoryRouter>)
    await user.click(screen.getByRole('button', { name: 'Open AI shopping assistant' }))
    await user.type(screen.getByRole('textbox', { name: 'Ask about products' }), 'Find a bottle')
    await user.click(screen.getByRole('button', { name: 'Send message to AI assistant' }))

    expect(await screen.findByText('This bottle is in stock [Product ID: 12].')).toBeInTheDocument()
    expect(screen.getByText('Same-category options over budget')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Reusable glass bottle/ })).toHaveAttribute('href', '/product/12')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/ai/chat/stream',
      expect.objectContaining({ method: 'POST', credentials: 'omit' }),
    )
  })

  it('formats streamed Markdown including lists and tables without rendering raw HTML', async () => {
    const user = userEvent.setup()
    const markdown = [
      '## Options',
      '',
      '**Phone A** is available.',
      '',
      '- In stock',
      '- Good value',
      '',
      '| Product | Price |',
      '| --- | ---: |',
      '| Phone A | $300 |',
      '',
      '<img src=x onerror=alert(1)>',
    ].join('\n')
    const events = [
      `data: ${JSON.stringify({ type: 'sources', sources: [] })}\n\n`,
      `data: ${JSON.stringify({ type: 'token', text: markdown })}\n\n`,
      'data: {"type":"done"}\n\n',
    ]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      body: new ReadableStream({
        start(controller) {
          for (const event of events) controller.enqueue(new TextEncoder().encode(event))
          controller.close()
        },
      }),
    }))
    render(<MemoryRouter><AiChatAssistant /></MemoryRouter>)
    await user.click(screen.getByRole('button', { name: 'Open AI shopping assistant' }))
    await user.type(screen.getByRole('textbox', { name: 'Ask about products' }), 'Compare phones')
    await user.click(screen.getByRole('button', { name: 'Send message to AI assistant' }))

    expect(await screen.findByRole('heading', { name: 'Options' })).toBeInTheDocument()
    expect(screen.getByText('Phone A', { selector: 'strong' })).toBeInTheDocument()
    expect(screen.getByRole('list')).toBeInTheDocument()
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })
})
