import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import { AdminProductEditor } from '@/components/AdminProductEditor'

afterEach(() => vi.restoreAllMocks())

describe('admin AI product content', () => {
  it('fills the description and unified features field from the AI endpoint', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.spyOn(api, 'post').mockResolvedValue({
      data: {
        success: true,
        message: 'queued',
        data: { id: 'ai-job-1', status: 'queued', progress: 0 },
      },
    } as never)
    vi.spyOn(api, 'get').mockResolvedValue({
      data: {
        success: true,
        message: 'completed',
        data: {
          id: 'ai-job-1',
          task_type: 'ai_product_content',
          resource_id: null,
          status: 'completed',
          progress: 100,
          result: {
            description: 'A considered everyday product.',
            features: '- 8GB RAM\n- 256GB storage',
          },
          error: null,
          created_at: '',
          updated_at: '',
        },
      },
    } as never)
    render(<AdminProductEditor product={null} saving={false} onCancel={vi.fn()} onSave={vi.fn()} />)

    await user.type(screen.getByLabelText('Product name'), 'Reusable mug')
    await user.type(screen.getByLabelText('Price'), '18')
    await user.type(screen.getByLabelText('Brand'), 'Common Goods')
    await user.click(screen.getByRole('checkbox', { name: 'Electronics' }))
    await user.type(screen.getByLabelText('Features'), '8GB RAM, 256GB storage')
    await user.click(screen.getByRole('button', { name: 'AI Generate Description & Features' }))

    expect(await screen.findByLabelText('Description')).toHaveValue('A considered everyday product.')
    expect(screen.getByLabelText('Features')).toHaveValue('- 8GB RAM\n- 256GB storage')
    expect(api.post).toHaveBeenCalledWith('/ai/products/generate-content/jobs', {
      name: 'Reusable mug',
      price: 18,
      stock: 0,
      brand: 'Common Goods',
      category: 'Electronics',
      features: '8GB RAM, 256GB storage',
      existing_description: null,
    })
    expect(api.get).toHaveBeenCalledWith('/jobs/ai-job-1')
  })

  it('does not replace existing generated edits without confirmation', async () => {
    const user = userEvent.setup()
    const post = vi.spyOn(api, 'post')
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<AdminProductEditor product={{
      id: 1, name: 'Existing item', description: 'Admin-written description',
      brand: null, category: null, feature_details: 'Wood',
      features: 'Hand-finished', specifications: { Material: 'Wood' },
      price: 20, stock: 1, image_url: null, owner_id: 1, created_at: '',
    }} saving={false} onCancel={vi.fn()} onSave={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: 'AI Generate Description & Features' }))

    expect(post).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Description')).toHaveValue('Admin-written description')
    expect(screen.getByLabelText('Features')).toHaveValue('Hand-finished')
  })

  it('submits approved generic product details and editable generated fields', () => {
    const onSave = vi.fn().mockResolvedValue(undefined)
    render(<AdminProductEditor product={null} saving={false} onCancel={vi.fn()} onSave={onSave} />)

    fireEvent.change(screen.getByLabelText('Product name'), { target: { value: 'Desk lamp' } })
    fireEvent.change(screen.getByLabelText('Brand'), { target: { value: 'Studio' } })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Furniture' }))
    fireEvent.change(screen.getByLabelText('Price'), { target: { value: '50' } })
    fireEvent.change(screen.getByLabelText('Stock'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('Features'), { target: { value: 'Brass finish, adjustable arm' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create product' }))

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      values: expect.objectContaining({
        name: 'Desk lamp',
        brand: 'Studio',
        categories: ['Furniture'],
        features: 'Brass finish, adjustable arm',
        price: 50,
        stock: 2,
      }),
    }))
  })

  it('allows up to three manually selected standard categories', () => {
    const onSave = vi.fn().mockResolvedValue(undefined)
    render(<AdminProductEditor product={null} saving={false} onCancel={vi.fn()} onSave={onSave} />)

    fireEvent.change(screen.getByLabelText('Product name'), { target: { value: 'Category test item' } })
    fireEvent.change(screen.getByLabelText('Price'), { target: { value: '12' } })
    fireEvent.change(screen.getByLabelText('Stock'), { target: { value: '1' } })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Electronics' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Footwear' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Furniture' }))

    expect(screen.getByRole('checkbox', { name: 'Clothing' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Create product' }))

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      values: expect.objectContaining({
        categories: ['Electronics', 'Footwear', 'Furniture'],
      }),
    }))
  })
})
