import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ProductImage } from '@/components/ProductImage'
import type { Product } from '@/types/models'

const product: Product = {
  id: 1,
  name: 'Everyday bottle',
  description: null,
  price: 12,
  stock: 5,
  image_url: null,
  owner_id: 1,
  created_at: '',
}

describe('ProductImage', () => {
  it('lazy loads images by default', () => {
    render(<ProductImage product={product} />)

    const image = screen.getByRole('img', { name: product.name })
    expect(image).toHaveAttribute('loading', 'lazy')
    expect(image).toHaveAttribute('decoding', 'async')
  })

  it('allows above-the-fold product images to load eagerly', () => {
    render(<ProductImage product={product} loading="eager" fetchPriority="high" />)

    const image = screen.getByRole('img', { name: product.name })
    expect(image).toHaveAttribute('loading', 'eager')
    expect(image).toHaveAttribute('fetchpriority', 'high')
  })
})
