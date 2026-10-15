import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { StorefrontPage } from '@/pages/StorefrontPage'
import { useAuthStore } from '@/stores/auth-store'
import type { ApiEnvelope, Paginated, Product } from '@/types/models'
import { server } from './mocks/server'

const sampleProducts: Product[] = [
  {
    id: 1, name: 'Everyday phone', description: 'A mobile phone', category: 'Electronics', categories: ['Electronics'],
    price: 200, stock: 3, image_url: null, owner_id: 1, created_at: '',
  },
  {
    id: 2, name: 'Canvas sneakers', description: 'Comfortable shoes', category: 'Footwear', categories: ['Footwear'],
    price: 80, stock: 3, image_url: null, owner_id: 1, created_at: '',
  },
]

function renderStorefront() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><StorefrontPage /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('storefront category navigation', () => {
  it('shows categories even when the catalogue has no matching products and filters when selected', async () => {
    const seenCategories: string[] = []
    useAuthStore.setState({ token: null, user: null, loading: false })
    server.use(
      http.get('/api/products/categories', () => HttpResponse.json({
        success: true,
        message: 'ok',
        data: [
          { name: 'Electronics', icon: 'laptop' },
          { name: 'Footwear', icon: 'footprints' },
        ],
      })),
      http.get('/api/products/', ({ request }) => {
        const category = new URL(request.url).searchParams.get('category') ?? ''
        seenCategories.push(category)
        const items = category === 'Footwear'
          ? sampleProducts.filter((product) => product.categories?.includes('Footwear'))
          : sampleProducts
        return HttpResponse.json<ApiEnvelope<Paginated<Product>>>({
          success: true,
          message: 'ok',
          data: { page: 1, limit: 12, total: items.length, items },
        })
      }),
    )

    renderStorefront()
    expect(await screen.findByRole('button', { name: 'Electronics' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Footwear' })).toBeInTheDocument()
    expect(await screen.findByText('Everyday phone')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Footwear' }))
    expect(await screen.findByText('Canvas sneakers')).toBeInTheDocument()
    await waitFor(() => expect(seenCategories).toContain('Footwear'))
    expect(screen.queryByText('Everyday phone')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'All products' }))
    expect(await screen.findByText('Everyday phone')).toBeInTheDocument()
    await waitFor(() => expect(seenCategories[seenCategories.length - 1]).toBe(''))
  })
})
