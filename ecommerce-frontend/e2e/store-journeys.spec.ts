import { expect, test, type Page, type Route } from '@playwright/test'
import type { BackgroundJob, CartItem, Order, Product, ShippingAddress, User } from '../src/types/models'

interface StoreApiOptions {
  products?: Product[]
  cart?: CartItem[]
  orders?: Order[]
  loginFailure?: boolean
  catalogFailure?: boolean
  realtimeEvents?: Array<{ type: string; data: Record<string, unknown> }>
  onWebSocketMessage?: (message: string) => void
  onOrderCreated?: (payload: { shipping_address: ShippingAddress; payment_method?: string; items?: Array<{ product_id: number; quantity: number }> }) => void
}

const shippingAddress: ShippingAddress = {
  full_name: 'Taylor Guest',
  email: 'shopper@example.com',
  phone: '+1 555 010 0150',
  address_line: '10 Example Street',
  city: 'Example City',
  postal_code: '10001',
  country: 'Example Country',
}

function product(id: number, name: string, price: number, stock = 6): Product {
  return {
    id,
    name,
    description: `${name}, made for everyday use.`,
    price,
    stock,
    image_url: null,
    owner_id: 1,
    created_at: '2026-01-01T00:00:00Z',
  }
}

function order(id: number, status: Order['status'] = 'Pending'): Order {
  return {
    id,
    user_id: 11,
    customer: { name: 'Taylor Guest', email: 'shopper@example.com' },
    total_amount: 24,
    status,
    created_at: '2026-01-01T00:00:00Z',
    shipping_address: shippingAddress,
    payment_method: 'card',
    items: [{ id: 1, product_id: 4, product_name: 'Linen market tote', quantity: 1, price: 24 }],
  }
}

const initialProducts = [
  product(4, 'Linen market tote', 24),
  product(5, 'Everyday mug', 12.5),
  product(6, 'Stoneware serving plate', 36),
]

function envelope<T>(data: T) {
  return { success: true, message: 'ok', data }
}

function multipartField(body: string, name: string): string {
  const marker = `name="${name}"\r\n\r\n`
  const start = body.indexOf(marker)
  if (start < 0) return ''
  const valueStart = start + marker.length
  const valueEnd = body.indexOf('\r\n', valueStart)
  return body.slice(valueStart, valueEnd < 0 ? undefined : valueEnd)
}

async function mockStoreApi(page: Page, options: StoreApiOptions = {}) {
  let products = [...(options.products ?? initialProducts)]
  let cart = [...(options.cart ?? [])]
  let orders = [...(options.orders ?? [])]
  const jobs: BackgroundJob[] = []
  let activeUser: User | null = null
  let nextOrderId = Math.max(80, ...orders.map((entry) => entry.id)) + 1

  await page.route('https://images.unsplash.com/**', (route) => route.abort())
  await page.routeWebSocket('**/ws*', (webSocket) => {
    webSocket.onMessage((message) => options.onWebSocketMessage?.(String(message)))
    for (const event of options.realtimeEvents ?? []) webSocket.send(JSON.stringify(event))
  })
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^\/api/, '')
    const method = request.method()

    if (path === '/auth/login' && method === 'POST') {
      if (options.loginFailure) {
        await route.fulfill({ status: 401, json: { detail: 'Invalid email or password.' } })
        return
      }
      const body = request.postDataJSON() as { email: string }
      const isAdmin = body.email.startsWith('admin')
      activeUser = {
        id: 11,
        name: isAdmin ? 'Store Admin' : 'Taylor Guest',
        email: body.email,
        role: isAdmin ? 'admin' : 'user',
      }
      await route.fulfill({ json: envelope({ access_token: 'test-access', refresh_token: 'test-refresh', token_type: 'bearer' }) })
      return
    }
    if (path === '/auth/register' && method === 'POST') {
      await route.fulfill({ json: envelope({ created: true }) })
      return
    }
    if (path === '/auth/me' && method === 'GET') {
      if (!activeUser && request.headers().authorization === 'Bearer e2e-customer-token') {
        activeUser = { id: 11, name: 'Taylor Guest', email: 'shopper@example.com', role: 'user' }
      } else if (!activeUser && request.headers().authorization === 'Bearer e2e-admin-token') {
        activeUser = { id: 1, name: 'Store Admin', email: 'admin@example.com', role: 'admin' }
      }
      await route.fulfill({ json: envelope(activeUser) })
      return
    }
    if (path === '/products/' && method === 'GET') {
      if (options.catalogFailure) {
        await route.fulfill({ status: 503, json: { detail: 'Catalog unavailable.' } })
        return
      }
      const search = url.searchParams.get('search')?.toLowerCase() ?? ''
      const minPrice = Number(url.searchParams.get('min_price') ?? 0)
      const maxPrice = Number(url.searchParams.get('max_price') ?? Infinity)
      const stockAvailable = url.searchParams.get('stock_available')
      const matching = products.filter((entry) =>
        entry.name.toLowerCase().includes(search)
        && entry.price >= minPrice
        && entry.price <= maxPrice
        && (stockAvailable === null || (entry.stock > 0) === (stockAvailable === 'true')),
      )
      const pageNumber = Number(url.searchParams.get('page') ?? 1)
      const limit = Number(url.searchParams.get('limit') ?? 12)
      await route.fulfill({
        json: envelope({
          page: pageNumber,
          limit,
          total: matching.length,
          items: matching.slice((pageNumber - 1) * limit, pageNumber * limit),
        }),
      })
      return
    }
    const productMatch = path.match(/^\/products\/(\d+)$/)
    if (productMatch && method === 'GET') {
      const found = products.find((entry) => entry.id === Number(productMatch[1]))
      await route.fulfill(found ? { json: envelope(found) } : { status: 404, json: { detail: 'Product not found.' } })
      return
    }
    if (path === '/cart/' && method === 'GET') {
      const currentCart = cart.map((entry) => ({
        ...entry,
        image_url: products.find((candidate) => candidate.id === entry.product_id)?.image_url ?? null,
      }))
      await route.fulfill({ json: envelope(currentCart) })
      return
    }
    if (path === '/chats/' && method === 'GET') {
      await route.fulfill({ json: envelope([]) })
      return
    }
    if (path === '/jobs/' && method === 'GET') {
      await route.fulfill({ json: envelope(jobs) })
      return
    }
    if (path === '/jobs/imports/products' && method === 'POST') {
      const job: BackgroundJob = {
        id: 'csv-import-job-1',
        task_type: 'product_import',
        resource_id: null,
        status: 'queued',
        progress: 0,
        result: null,
        error: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      jobs.unshift(job)
      setTimeout(() => {
        job.status = 'completed'
        job.progress = 100
        job.result = { imported: 2, processed: 2, error_count: 0, errors: [] }
        job.updated_at = new Date().toISOString()
      }, 400)
      await route.fulfill({ json: envelope(job) })
      return
    }
    const invoiceJobMatch = path.match(/^\/jobs\/invoices\/(\d+)$/)
    if (invoiceJobMatch && method === 'POST') {
      const job: BackgroundJob = {
        id: `invoice-job-${invoiceJobMatch[1]}`,
        task_type: 'invoice',
        resource_id: Number(invoiceJobMatch[1]),
        status: 'completed',
        progress: 100,
        result: { order_id: Number(invoiceJobMatch[1]), total_amount: 24, download_url: `/jobs/invoices/${invoiceJobMatch[1]}/download` },
        error: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      jobs.unshift(job)
      await route.fulfill({ json: envelope(job) })
      return
    }
    if (path === '/cart/add' && method === 'POST') {
      const productId = Number(url.searchParams.get('product_identifier'))
      const quantity = Number(url.searchParams.get('quantity') ?? 1)
      const selected = products.find((entry) => entry.id === productId)
      if (!selected) {
        await route.fulfill({ status: 404, json: { detail: 'Product not found.' } })
        return
      }
      const existing = cart.find((entry) => entry.product_id === productId)
      cart = existing
        ? cart.map((entry) => entry.product_id === productId
          ? { ...entry, quantity: entry.quantity + quantity, total_price: entry.price * (entry.quantity + quantity) }
          : entry)
        : [...cart, {
          product_id: selected.id,
          name: selected.name,
          description: selected.description,
          image_url: selected.image_url,
          price: selected.price,
          quantity,
          total_price: selected.price * quantity,
        }]
      await route.fulfill({ json: envelope({ [String(productId)]: quantity }) })
      return
    }
    if (path === '/cart/edit' && method === 'PUT') {
      const productId = Number(url.searchParams.get('product_id'))
      const quantity = Number(url.searchParams.get('quantity'))
      cart = quantity === 0
        ? cart.filter((entry) => entry.product_id !== productId)
        : cart.map((entry) => entry.product_id === productId
          ? { ...entry, quantity, total_price: entry.price * quantity }
          : entry)
      await route.fulfill({ json: envelope(cart) })
      return
    }
    const removeMatch = path.match(/^\/cart\/remove\/(\d+)$/)
    if (removeMatch && method === 'DELETE') {
      cart = cart.filter((entry) => entry.product_id !== Number(removeMatch[1]))
      await route.fulfill({ json: envelope(cart) })
      return
    }
    if (path === '/orders/' && method === 'POST') {
      const body = request.postDataJSON() as { shipping_address: ShippingAddress; payment_method?: string; items?: Array<{ product_id: number; quantity: number }> }
      options.onOrderCreated?.(body)
      const placed = order(nextOrderId++)
      placed.shipping_address = body.shipping_address
      placed.payment_method = body.payment_method as Order['payment_method']
      const purchased: Array<{ product_id: number; name: string; price: number; quantity: number }> = body.items?.flatMap((item) => {
        const entry = products.find((candidate) => candidate.id === item.product_id)
        return entry ? [{ product_id: entry.id, name: entry.name, price: entry.price, quantity: item.quantity }] : []
      }) ?? cart.map((entry) => ({ product_id: entry.product_id, name: entry.name, price: entry.price, quantity: entry.quantity }))
      placed.items = purchased.map((entry, index) => ({
        id: index + 1,
        product_id: entry.product_id,
        product_name: entry.name,
        quantity: entry.quantity,
        price: entry.price,
      }))
      placed.total_amount = purchased.reduce((total, entry) => total + entry.price * entry.quantity, 0)
      orders = [placed, ...orders]
      if (!body.items) cart = []
      await route.fulfill({ json: envelope(placed) })
      return
    }
    if (path === '/orders/' && method === 'GET') {
      await route.fulfill({ json: envelope(orders) })
      return
    }
    if (path === '/orders/admin/all' && method === 'GET') {
      await route.fulfill({ json: envelope(orders) })
      return
    }
    const orderActionMatch = path.match(/^\/orders\/(\d+)\/(cancel|complete|status)$/)
    if (orderActionMatch && method === 'PATCH') {
      const orderId = Number(orderActionMatch[1])
      const body = request.postDataJSON() as { status?: Order['status'] } | null
      const status = orderActionMatch[2] === 'cancel'
        ? 'Cancelled'
        : orderActionMatch[2] === 'status'
          ? body?.status ?? 'Pending'
          : 'Completed'
      orders = orders.map((entry) => entry.id === orderId ? { ...entry, status } : entry)
      await route.fulfill({ json: envelope(orders.find((entry) => entry.id === orderId) ?? null) })
      return
    }
    if (path === '/products/' && method === 'POST') {
      const body = request.postData() ?? ''
      const created = product(
        Math.max(0, ...products.map((entry) => entry.id)) + 1,
        multipartField(body, 'name'),
        Number(multipartField(body, 'price')),
        Number(multipartField(body, 'stock')),
      )
      created.description = multipartField(body, 'description')
      created.image_url = multipartField(body, 'image_url') || null
      products = [...products, created]
      await route.fulfill({ json: envelope(created) })
      return
    }
    const imageUploadMatch = path.match(/^\/products\/(\d+)\/image$/)
    if (imageUploadMatch && method === 'POST') {
      const productId = Number(imageUploadMatch[1])
      products = products.map((entry) => entry.id === productId ? { ...entry, image_url: 'app/uploads/products/test-image.webp' } : entry)
      await route.fulfill({ json: envelope(products.find((entry) => entry.id === productId) ?? null) })
      return
    }
    const productWriteMatch = path.match(/^\/products\/(\d+)$/)
    if (productWriteMatch && method === 'PUT') {
      const productId = Number(productWriteMatch[1])
      const body = request.postDataJSON() as Pick<Product, 'name' | 'description' | 'price' | 'stock'>
      products = products.map((entry) => entry.id === productId ? { ...entry, ...body } : entry)
      await route.fulfill({ json: envelope(products.find((entry) => entry.id === productId) ?? null) })
      return
    }
    if (productWriteMatch && method === 'DELETE') {
      products = products.filter((entry) => entry.id !== Number(productWriteMatch[1]))
      await route.fulfill({ json: envelope(null) })
      return
    }

    await route.fulfill({ status: 404, json: { detail: `Unmocked test endpoint: ${method} ${path}` } })
  })
}

async function signIn(page: Page, email = 'shopper@example.com') {
  await page.goto('/login')
  await page.getByLabel('Email address').fill(email)
  await page.getByLabel('Password').fill('test-password9!')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.locator('.site-header')).toBeVisible()
}

async function fillDeliveryAddress(page: Page) {
  await page.getByLabel('Phone').fill(shippingAddress.phone)
  await page.getByLabel('Street address').fill(shippingAddress.address_line)
  await page.getByLabel('City').fill(shippingAddress.city)
  await page.getByLabel('Postal code').fill(shippingAddress.postal_code)
  await page.getByLabel('Country').fill(shippingAddress.country)
}

test('shows the collection and opens a product detail', async ({ page }) => {
  await mockStoreApi(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /Everyday things/ })).toBeVisible()
  await expect(page.locator('.product-card')).toHaveCount(3)
  await page.getByRole('link', { name: 'View Linen market tote' }).click()
  await expect(page.getByRole('heading', { name: 'Linen market tote' })).toBeVisible()
  await expect(page.getByText('CG-0004')).toBeVisible()
})

test('searches the catalog using the API query', async ({ page }) => {
  await mockStoreApi(page)
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Search products' }).fill('mug')
  await expect(page.locator('.product-card')).toHaveCount(1)
  await expect(page.getByRole('link', { name: 'Everyday mug', exact: true })).toBeVisible()
  await expect(page.getByRole('listbox', { name: 'Matching products' }).getByRole('option', { name: /Everyday mug/ })).toBeVisible()
  await expect(page.getByLabel('Search matching')).toHaveCount(0)
})

test('shows a toast and notification when a CSV import completes', async ({ page }) => {
  await mockStoreApi(page)
  await signIn(page, 'admin@example.com')
  await page.getByRole('link', { name: 'Admin' }).click()
  await page.getByRole('tab', { name: 'Products' }).click()
  await page.locator('#product-csv-file').setInputFiles({
    name: 'products.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('name,price,stock\nNew mug,12.50,8\n'),
  })
  await page.getByRole('button', { name: 'Start import' }).click()
  await expect(page).toHaveURL(/\/jobs$/)
  await expect(page.getByText('CSV import complete')).toBeVisible({ timeout: 6000 })
  await expect(page.getByText('Imported 2 of 2 rows')).toBeVisible()
  await page.getByRole('button', { name: 'Open notifications' }).click()
  await expect(page.getByRole('region', { name: 'Notifications', exact: true })).toContainText('Successfully imported 2 products.')
})

test('shows a toast and notification when invoice generation completes', async ({ page }) => {
  await mockStoreApi(page, { orders: [order(90)] })
  await signIn(page)
  await page.getByRole('link', { name: 'Your orders' }).click()
  await page.getByRole('button', { name: 'Generate invoice' }).click()
  await expect(page).toHaveURL(/\/jobs$/)
  await expect(page.getByText('Invoice PDF ready')).toBeVisible({ timeout: 6000 })
  await page.getByRole('button', { name: 'Open notifications' }).click()
  await expect(page.getByRole('region', { name: 'Notifications', exact: true })).toContainText('Invoice PDF for order #90 is ready to download.')
})

test('sorts products by ascending price', async ({ page }) => {
  await mockStoreApi(page)
  await page.goto('/')
  await page.getByLabel('Sort products').selectOption('price-low')
  await expect(page.locator('.product-card .product-name').first()).toHaveText('Everyday mug')
  await expect(page.locator('.product-card .product-name').last()).toHaveText('Stoneware serving plate')
})

test('redirects unauthenticated shoppers back to their protected cart after sign-in', async ({ page }) => {
  await mockStoreApi(page)
  await page.goto('/cart')
  await expect(page).toHaveURL(/\/login$/)
  await page.getByLabel('Email address').fill('shopper@example.com')
  await page.getByLabel('Password').fill('test-password9!')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/cart$/)
  await expect(page.getByRole('heading', { level: 1, name: /^Your bag/ })).toBeVisible()
})

test('validates required sign-in details before sending a request', async ({ page }) => {
  await mockStoreApi(page)
  await page.goto('/login')
  await page.getByLabel('Email address').fill('not-an-email')
  await page.getByLabel('Password').fill('short')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.locator('.field-error').filter({ hasText: 'Enter a valid email address.' })).toBeVisible()
  await expect(page.locator('.field-error').filter({ hasText: 'Password must contain at least 8 characters.' })).toBeVisible()
})

test('announces authentication API errors without navigating away', async ({ page }) => {
  await mockStoreApi(page, { loginFailure: true })
  await page.goto('/login')
  await page.getByLabel('Email address').fill('shopper@example.com')
  await page.getByLabel('Password').fill('test-password9!')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('alert')).toHaveText('Invalid email or password.')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
})

test('signs in a customer and exposes customer navigation', async ({ page }) => {
  await mockStoreApi(page)
  await signIn(page)
  await expect(page.getByText('Hi, Taylor')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Your orders' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Admin' })).toHaveCount(0)
})

test('registers a new account through the registration and sign-in flow', async ({ page }) => {
  await mockStoreApi(page)
  await page.goto('/register')
  await page.getByLabel('Your name').fill('Taylor Guest')
  await page.getByLabel('Email address').fill('new-shopper@example.com')
  await page.getByLabel('Password').fill('new-password9!')
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page.getByText('Hi, Taylor')).toBeVisible()
  await expect(page.getByRole('heading', { name: /Everyday things/ })).toBeVisible()
})

test.describe('authenticated customer journeys', () => {
test.use({ storageState: 'playwright/.auth/customer.json' })

test('changes product quantity and adds that quantity to the server cart', async ({ page }) => {
  await mockStoreApi(page)
  await page.goto('/product/4')
  await expect(page.getByRole('heading', { name: 'Linen market tote' })).toBeVisible()
  await page.getByRole('button', { name: 'Increase quantity' }).click()
  await expect(page.getByText('2', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Add to bag' }).click()
  await expect(page.getByRole('link', { name: 'Shopping bag, 2 items' })).toBeVisible()
})

test('buys a product directly and completes demo UPI checkout without adding it to the cart', async ({ page }) => {
  let submitted: { shipping_address: ShippingAddress; payment_method?: string; items?: Array<{ product_id: number; quantity: number }> } | undefined
  await mockStoreApi(page, { onOrderCreated: (payload) => { submitted = payload } })
  await page.goto('/product/4')
  await page.getByRole('button', { name: 'Increase quantity' }).click()
  await page.getByRole('button', { name: 'Buy now' }).click()
  await expect(page).toHaveURL(/\/payments\?product_id=4&quantity=2/)
  await expect(page.getByRole('heading', { name: 'Checkout' })).toBeVisible()
  await page.getByRole('radio', { name: 'UPI' }).click()
  await page.getByLabel('UPI ID').fill('taylor@bank')
  await fillDeliveryAddress(page)
  await page.getByRole('button', { name: /Place order/ }).click()
  await expect(page.getByRole('heading', { name: 'Your orders' })).toBeVisible()
  expect(submitted?.payment_method).toBe('upi')
  expect(submitted?.items).toEqual([{ product_id: 4, quantity: 2 }])
  await expect(page.getByRole('link', { name: 'Shopping bag, 0 items' })).toBeVisible()
})

test('accepts demo card details without sending them to the order API', async ({ page }) => {
  let submitted: { shipping_address: ShippingAddress; payment_method?: string; items?: Array<{ product_id: number; quantity: number }> } | undefined
  await mockStoreApi(page, { onOrderCreated: (payload) => { submitted = payload } })
  await page.goto('/product/4')
  await page.getByRole('button', { name: 'Buy now' }).click()
  await page.getByRole('radio', { name: 'Card' }).click()
  await page.getByLabel('Card number').fill('4242 4242 4242 4242')
  await expect(page.getByLabel('Card number')).toHaveValue('4242 4242 4242 4242')
  await page.getByLabel('Expiry (MM/YY)').fill('1230')
  await expect(page.getByLabel('Expiry (MM/YY)')).toHaveValue('12/30')
  await page.getByLabel('Security code').fill('123')
  await fillDeliveryAddress(page)
  await page.getByRole('button', { name: /Place order/ }).click()
  await expect(page.getByRole('heading', { name: 'Your orders' })).toBeVisible()
  expect(submitted?.payment_method).toBe('card')
  expect(JSON.stringify(submitted)).not.toContain('4242')
  expect(JSON.stringify(submitted)).not.toContain('123')
})

test('rejects an expired card without creating an order', async ({ page }) => {
  let submitted = false
  await mockStoreApi(page, { onOrderCreated: () => { submitted = true } })
  await page.goto('/product/4')
  await page.getByRole('button', { name: 'Buy now' }).click()
  await page.getByRole('radio', { name: 'Card' }).click()
  await page.getByLabel('Card number').fill('4242424242424242')
  await page.getByLabel('Expiry (MM/YY)').fill('0120')
  await page.getByLabel('Security code').fill('123')
  await fillDeliveryAddress(page)
  await page.getByRole('button', { name: /Place order/ }).click()
  await expect(page.getByRole('alert')).toContainText('Enter a valid, unexpired card expiry date.')
  expect(submitted).toBe(false)
})

test('updates cart quantities and recalculates line and subtotal amounts', async ({ page }) => {
  const cart: CartItem[] = [{
    product_id: 4, name: 'Linen market tote', description: 'A daily carryall.',
    price: 24, quantity: 1, total_price: 24,
  }]
  await mockStoreApi(page, { cart })
  await page.goto('/cart')
  await page.getByRole('button', { name: 'Increase Linen market tote quantity' }).click()
  await expect(page.locator('.cart-item-controls strong')).toHaveText('₹48.00')
  await expect(page.locator('.summary-total b')).toHaveText('₹48.00')
})

test('shows the latest product image in the bag after the product was updated', async ({ page }) => {
  const latestImage = 'https://images.example.test/latest-tote.jpg'
  const updatedProduct = { ...product(4, 'Linen market tote', 24), image_url: latestImage }
  const cart: CartItem[] = [{
    product_id: 4, name: 'Linen market tote', description: 'A daily carryall.',
    image_url: 'https://images.example.test/old-tote.jpg',
    price: 24, quantity: 1, total_price: 24,
  }]
  await mockStoreApi(page, { products: [updatedProduct], cart })
  await page.route('https://images.example.test/**', (route) => route.fulfill({
    status: 200,
    contentType: 'image/svg+xml',
    body: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect width="1" height="1" /></svg>',
  }))
  await page.goto('/cart')
  await expect(page.locator('.cart-item-image img')).toHaveAttribute('src', latestImage)
})

test('removes cart items and displays the empty-cart state', async ({ page }) => {
  const cart: CartItem[] = [{
    product_id: 4, name: 'Linen market tote', description: 'A daily carryall.',
    price: 24, quantity: 1, total_price: 24,
  }]
  await mockStoreApi(page, { cart })
  await page.goto('/cart')
  await page.getByRole('button', { name: 'Remove' }).click()
  await expect(page.getByText('Your bag is taking a breather.')).toBeVisible()
})

test('validates checkout address fields and does not create an invalid order', async ({ page }) => {
  const cart: CartItem[] = [{
    product_id: 4, name: 'Linen market tote', description: 'A daily carryall.',
    price: 24, quantity: 1, total_price: 24,
  }]
  await mockStoreApi(page, { cart })
  await page.goto('/checkout')
  await page.getByRole('button', { name: /Place order/ }).click()
  await expect(page.getByText('Enter a valid phone number.')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Checkout' })).toBeVisible()
})

test('places an order with validated delivery details and shows it in order history', async ({ page }) => {
  const cart: CartItem[] = [{
    product_id: 4, name: 'Linen market tote', description: 'A daily carryall.',
    price: 24, quantity: 1, total_price: 24,
  }]
  await mockStoreApi(page, { cart })
  await page.goto('/checkout')
  await fillDeliveryAddress(page)
  await page.getByRole('button', { name: /Place order/ }).click()
  await expect(page.getByRole('heading', { name: 'Your orders' })).toBeVisible()
  await expect(page.getByText('Order #00081')).toBeVisible()
  await expect(page.getByText('10 Example Street')).toBeVisible()
  await expect(page.locator('.order-card .order-footer strong')).toHaveText('₹24.00')
  await expect(page.locator('.order-payment')).toContainText('Cash on delivery')
  await expect(page.locator('.order-payment')).toContainText('no payment was processed')
})

test('shows previous order details and lets a customer cancel a pending order', async ({ page }) => {
  await mockStoreApi(page, { orders: [order(81)] })
  await page.goto('/orders')
  await expect(page.getByText('Order #00081')).toBeVisible()
  await expect(page.getByText('10 Example Street')).toBeVisible()
  await expect(page.locator('.order-payment')).toContainText('Card')
  await expect(page.locator('.order-payment')).toContainText('no payment was processed')
  await page.getByRole('button', { name: 'Cancel order' }).click()
  await expect(page.getByText('Cancelled', { exact: true })).toBeVisible()
})

test('prevents customer accounts from entering the admin dashboard', async ({ page }) => {
  await mockStoreApi(page)
  await page.goto('/admin')
  await expect(page).toHaveURL('/')
  await expect(page.getByRole('heading', { name: /Everyday things/ })).toBeVisible()
})

test('keeps live notifications and support chat in separate panels', async ({ page }) => {
  let sentMessage = ''
  await mockStoreApi(page, {
    realtimeEvents: [
      { type: 'notification', data: { title: 'Order update', message: 'Order #81 is now completed.' } },
      { type: 'chat.message', data: {
        sender_id: 1, sender_name: 'Store Admin', recipient_id: 11,
        text: 'How can we help?', created_at: '2026-01-01T00:00:00Z',
      } },
    ],
    onWebSocketMessage: (message) => { sentMessage = message },
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Open notifications' }).click()
  const notifications = page.getByRole('region', { name: 'Notifications', exact: true })
  await expect(notifications.getByText('Order #81 is now completed.')).toBeVisible()
  await expect(notifications.getByText('How can we help?')).toHaveCount(0)
  await page.getByRole('button', { name: 'Open live support' }).click()
  const support = page.getByRole('region', { name: 'Live support' })
  await expect(support.getByText('How can we help?')).toBeVisible()
  await expect(support.getByText('Order #81 is now completed.')).toHaveCount(0)
  await page.getByLabel('Support message').fill('I need help with my order.')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect.poll(() => sentMessage).toContain('"type":"chat.send"')
  await expect.poll(() => sentMessage).toContain('I need help with my order.')
})
})

test.describe('authenticated admin journeys', () => {
test.use({ storageState: 'playwright/.auth/admin.json' })

test('loads catalog items in the admin dashboard within the API page-size limit', async ({ page }) => {
  let requestedCatalogLimit: string | null = null
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname === '/api/products/') {
      requestedCatalogLimit = url.searchParams.get('limit')
    }
  })
  await mockStoreApi(page)
  await page.goto('/admin')
  await page.getByRole('tab', { name: /Products/ }).click()

  await expect(page.getByRole('heading', { name: 'Linen market tote' })).toBeVisible()
  expect(requestedCatalogLimit).toBe('100')
})

test('moves orders through each fulfillment status in its matching group', async ({ page }) => {
  await mockStoreApi(page, { orders: [order(81)] })
  await page.goto('/admin')
  await expect(page.getByRole('heading', { name: 'Admin dashboard' })).toBeVisible()
  await expect(page.getByText('Taylor Guest')).toBeVisible()
  const steps = [
    { group: 'Pending', button: 'Pack order' },
    { group: 'Packed', button: 'Ship order' },
    { group: 'Shipped', button: 'Out for delivery' },
    { group: 'Out for Delivery', button: 'Mark delivered' },
    { group: 'Delivered', button: 'Complete order' },
  ]
  for (const step of steps) {
    await page.getByRole('button', { name: new RegExp(`^${step.group}`) }).click()
    const group = page.getByRole('region', { name: `${step.group} orders` })
    await expect(group.getByText('#00081', { exact: true })).toBeVisible()
    await group.getByRole('button', { name: step.button }).click()
  }
  await page.getByRole('button', { name: /^Completed/ }).click()
  await expect(page.getByRole('region', { name: 'Completed orders' }).getByText('#00081', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: /^Pending/ }).click()
  await expect(page.getByText('No pending orders.')).toBeVisible()
})

test('lets administrators cancel pending orders', async ({ page }) => {
  await mockStoreApi(page, { orders: [order(81)] })
  await page.goto('/admin')
  const adminOrders = page.getByRole('region', { name: 'All orders' })
  await expect(adminOrders.getByRole('columnheader', { name: 'Payment' })).toBeVisible()
  await expect(adminOrders.getByText('Card')).toBeVisible()
  await expect(adminOrders.getByText('Demo only · not processed')).toBeVisible()
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByText('Cancelled', { exact: true })).toBeVisible()
})

test('shows admins one new-order notification with the customer name', async ({ page }) => {
  await mockStoreApi(page, {
    realtimeEvents: [{
      type: 'notification',
      data: {
        title: 'New order',
        message: 'Order #81 was placed by Taylor Guest.',
        order_id: 81,
        user_id: 11,
        status: 'Pending',
        total_amount: 24,
      },
    }],
  })
  await page.goto('/admin')
  await page.getByRole('button', { name: 'Open notifications' }).click()
  const notifications = page.getByRole('region', { name: 'Notifications', exact: true })
  await expect(notifications.getByText('Order #81 was placed by Taylor Guest.')).toBeVisible()
  await expect(notifications.getByText('Your order #81 has been placed successfully.')).toHaveCount(0)
})

test('creates a catalog product from the admin dashboard with a previewed image URL', async ({ page }) => {
  await page.route('https://images.example.test/**', (route) => route.fulfill({
    contentType: 'image/png',
    body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l2cAAAAASUVORK5CYII=', 'base64'),
  }))
  await mockStoreApi(page)
  await page.goto('/admin')
  await page.getByRole('tab', { name: /Products/ }).click()
  await page.getByRole('button', { name: /Add product/ }).click()
  await page.getByLabel('Product name').fill('New ceramic bowl')
  await page.getByLabel('Price').fill('19.50')
  await page.getByLabel('Stock').fill('8')
  await page.getByLabel('Description').fill('A hand-finished serving bowl.')
  await page.getByRole('button', { name: 'Image URL' }).click()
  await page.getByLabel('Image URL').fill('https://images.example.test/ceramic-bowl.png')
  await expect(page.getByRole('img', { name: 'Product image preview' })).toBeVisible()
  await page.getByLabel('Image URL').fill('javascript:alert(1)')
  await expect(page.getByRole('button', { name: 'Create product' })).toBeDisabled()
  await page.getByLabel('Image URL').fill('https://images.example.test/ceramic-bowl.png')
  await expect(page.getByRole('button', { name: 'Create product' })).toBeEnabled()
  await page.getByRole('button', { name: 'Create product' }).click()
  await expect(page.getByText('New ceramic bowl')).toBeVisible()
  await expect(page.locator('.admin-product-card').filter({ hasText: 'New ceramic bowl' }).locator('.admin-product-card-image')).toHaveAttribute('src', 'https://images.example.test/ceramic-bowl.png')
})

test('edits a catalog product in place including its image URL, then removes it', async ({ page }) => {
  await page.route('https://images.example.test/**', (route) => route.fulfill({
    contentType: 'image/png',
    body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l2cAAAAASUVORK5CYII=', 'base64'),
  }))
  await mockStoreApi(page)
  await page.goto('/admin')
  await page.getByRole('tab', { name: /Products/ }).click()
  const productCard = page.locator('.admin-product-card').filter({ hasText: /Linen market tote|Updated linen tote/ })
  await productCard.getByRole('button', { name: 'Edit Linen market tote' }).click()
  await expect(productCard.locator('.admin-inline-editor')).toBeVisible()
  await productCard.getByLabel('Product name').fill('Updated linen tote')
  await productCard.getByRole('button', { name: 'Image URL' }).click()
  await productCard.getByLabel('Image URL').fill('https://images.example.test/updated-tote.png')
  await expect(productCard.getByRole('img', { name: 'Product image preview' })).toBeVisible()
  await productCard.getByRole('button', { name: 'Save product' }).click()
  await expect(page.getByText('Updated linen tote')).toBeVisible()
  await expect(productCard.locator('.admin-product-card-image')).toHaveAttribute('src', 'https://images.example.test/updated-tote.png')
  await productCard.getByRole('button', { name: 'Edit Updated linen tote' }).click()
  await productCard.getByRole('button', { name: 'Upload image' }).click()
  await productCard.locator('input[type="file"]').setInputFiles({
    name: 'updated-product.png',
    mimeType: 'image/png',
    buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l2cAAAAASUVORK5CYII=', 'base64'),
  })
  await expect(productCard.getByRole('img', { name: 'Selected product image preview' })).toBeVisible()
  await productCard.getByRole('button', { name: 'Save product' }).click()
  await expect(productCard.locator('.admin-product-card-image')).toHaveAttribute('src', '/api/uploads/products/test-image.webp')
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Delete Updated linen tote' }).click()
  await expect(page.getByText('Updated linen tote')).toHaveCount(0)
})
})

test('toggles dark mode and restores the saved preference after reload', async ({ page }) => {
  await mockStoreApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Switch to dark mode' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expect(page.getByRole('button', { name: 'Switch to light mode' })).toBeVisible()
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
})
