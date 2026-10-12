import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from './mocks/server'
import { useProducts } from '@/hooks/use-products'
import type { ApiEnvelope, Paginated, Product } from '@/types/models'

const product: Product = {
  id: 7,
  name: 'Stoneware cup',
  description: null,
  price: 18,
  stock: 2,
  image_url: null,
  owner_id: 1,
  created_at: '2026-01-01T00:00:00Z',
}

function createWrapper() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

describe('product query hook with mocked API', () => {
  it('fetches products from the typed API response', async () => {
    server.use(http.get('/api/products/', () => HttpResponse.json<ApiEnvelope<Paginated<Product>>>({
      success: true,
      message: 'ok',
      data: { page: 1, limit: 12, total: 1, items: [product] },
    })))

    const { result } = renderHook(() => useProducts(), { wrapper: createWrapper() })
    await waitFor(() => expect(result.current.data?.pages[0]?.items[0]?.name).toBe('Stoneware cup'))
  })

  it('uses next-page metadata to enable infinite scrolling', async () => {
    server.use(http.get('/api/products/', ({ request }) => {
      const page = Number(new URL(request.url).searchParams.get('page'))
      const data = { page, limit: 1, total: 2, items: [{ ...product, id: page }] }
      return HttpResponse.json({ success: true, message: 'ok', data })
    }))

    const { result } = renderHook(() => useProducts(), { wrapper: createWrapper() })
    await waitFor(() => expect(result.current.hasNextPage).toBe(true))
    await act(async () => { await result.current.fetchNextPage() })
    await waitFor(() => expect(result.current.data?.pages).toHaveLength(2))
    expect(result.current.hasNextPage).toBe(false)
  })

  it('surfaces server errors instead of returning an empty success result', async () => {
    server.use(http.get('/api/products/', () => HttpResponse.json({ detail: 'Catalog unavailable' }, { status: 503 })))
    const { result } = renderHook(() => useProducts(), { wrapper: createWrapper() })
    await waitFor(() => expect(result.current.isError).toBe(true))
  })

  it('routes semantic queries through the embedding search endpoint', async () => {
    server.use(http.get('/api/products/semantic-search', ({ request }) => {
      const url = new URL(request.url)
      expect(url.searchParams.get('q')).toBe('something for a warm drink')
      expect(url.searchParams.get('page')).toBe('1')
      return HttpResponse.json<ApiEnvelope<Paginated<Product>>>({
        success: true,
        message: 'ok',
        data: { page: 1, limit: 12, total: 1, items: [product] },
      })
    }))

    const { result } = renderHook(
      () => useProducts({ search: 'something for a warm drink', search_mode: 'semantic' }),
      { wrapper: createWrapper() },
    )

    await waitFor(() => expect(result.current.data?.pages[0]?.items[0]?.id).toBe(7))
  })
})
