import { http, HttpResponse } from 'msw'
import type { ApiEnvelope, CartItem, Order, Paginated, Product } from '@/types/models'

const envelope = <T,>(data: T): ApiEnvelope<T> => ({ success: true, message: 'ok', data })

export const handlers = [
  http.get('/api/cart/', () => HttpResponse.json(envelope<CartItem[]>([]))),
  http.get('/api/products/categories', () => HttpResponse.json(envelope([
    { name: 'Electronics', icon: 'laptop' },
    { name: 'Footwear', icon: 'footprints' },
  ]))),
  http.get('/api/products/', () => HttpResponse.json(envelope<Paginated<Product>>({
    page: 1,
    limit: 12,
    total: 0,
    items: [],
  }))),
  http.get('/api/orders/', () => HttpResponse.json(envelope<Order[]>([]))),
]
