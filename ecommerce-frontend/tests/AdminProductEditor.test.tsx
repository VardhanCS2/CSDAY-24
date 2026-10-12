import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import { AdminProductEditor } from '@/components/AdminProductEditor'

afterEach(() => vi.restoreAllMocks())

describe('admin AI product descriptions', () => {
  it('fills a reviewable description draft from the AI endpoint', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'post').mockResolvedValue({
      data: { success: true, message: 'ok', data: { description: 'A considered everyday product.' } },
    } as never)
    render(<AdminProductEditor product={null} saving={false} onCancel={vi.fn()} onSave={vi.fn()} />)

    await user.type(screen.getByLabelText('Product name'), 'Reusable mug')
    await user.type(screen.getByLabelText('Price'), '18')
    await user.click(screen.getByRole('button', { name: 'Generate with AI' }))

    expect(await screen.findByLabelText('Description')).toHaveValue('A considered everyday product.')
    expect(api.post).toHaveBeenCalledWith('/ai/products/generate-description', {
      name: 'Reusable mug',
      price: 18,
      details: '',
    })
  })
})
