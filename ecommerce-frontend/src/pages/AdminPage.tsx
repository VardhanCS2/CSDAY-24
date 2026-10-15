import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ArrowRight, CheckCircle2, ClipboardList, MessageCircle, PackagePlus, Pencil, RefreshCw, ShieldCheck, Trash2, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { api, errorMessage, responseData } from '@/api/client'
import { useOrderActions, useOrders } from '@/hooks/use-orders'
import { ProductImage } from '@/components/ProductImage'
import { AdminProductEditor, type ProductEditorValues } from '@/components/AdminProductEditor'
import { CsvImportPanel } from '@/components/CsvImportPanel'
import { Button } from '@/components/ui/button'
import { formatPaymentMethod, formatPrice } from '@/lib/utils'
import { useAuth } from '@/hooks/useAuth'
import type { Order, Paginated, Product } from '@/types/models'

type ProductSection = 'orders' | 'products'
type OrderFilter = 'All' | typeof orderStatuses[number]
interface SaveProductVariables { product: Product | null; submission: ProductEditorValues }
interface SaveProductContext {
  productsKey: readonly ['admin', 'products']
  previousList: Paginated<Product> | undefined
  productId?: number
  previousProduct?: Product
}
interface DeleteProductContext {
  productsKey: readonly ['admin', 'products']
  previousList: Paginated<Product> | undefined
}
const orderStatuses = ['Pending', 'Packed', 'Shipped', 'Out for Delivery', 'Delivered', 'Completed', 'Cancelled'] as const
type OrderStatus = typeof orderStatuses[number]
const nextOrderStep: Partial<Record<string, { status: OrderStatus; label: string }>> = {
  Pending: { status: 'Packed', label: 'Pack order' },
  Packed: { status: 'Shipped', label: 'Ship order' },
  Shipped: { status: 'Out for Delivery', label: 'Out for delivery' },
  'Out for Delivery': { status: 'Delivered', label: 'Mark delivered' },
  Delivered: { status: 'Completed', label: 'Complete order' },
}

export function AdminPage() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [section, setSection] = useState<ProductSection>('orders')
  const [orderFilter, setOrderFilter] = useState<OrderFilter>('All')
  const [creatingProduct, setCreatingProduct] = useState(false)
  const [editingProductId, setEditingProductId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [busyOrder, setBusyOrder] = useState<number | null>(null)
  const ordersQuery = useOrders({ admin: true })
  const productsQuery = useQuery({
    queryKey: ['admin', 'products'],
    queryFn: async () => responseData<Paginated<Product>>(await api.get('/products/', { params: { page: 1, limit: 100 } })),
  })
  const orders = ordersQuery.data || []
  const products = productsQuery.data?.items || []
  const loading = ordersQuery.isPending || productsQuery.isPending
  const orderMutation = useOrderActions({ admin: true })

  const saveProductMutation = useMutation<unknown, Error, SaveProductVariables, SaveProductContext>({
    mutationFn: async ({ product, submission }) => {
      const { values, image, imageMode } = submission
      if (product) {
        if (imageMode === 'upload' && image) {
          const payload = new FormData()
          payload.append('image', image)
          await api.post(`/products/${product.id}/image`, payload)
        }
        return api.put(`/products/${product.id}`, {
          name: values.name,
          description: values.description || null,
          brand: values.brand || null,
          category: values.categories[0] || null,
          categories: values.categories,
          feature_details: null,
          features: values.features || null,
          specifications: {},
          price: values.price,
          stock: values.stock,
          ...(imageMode === 'url' ? { image_url: values.image_url || null } : {}),
        })
      }
      const payload = new FormData()
      payload.append('name', values.name)
      payload.append('description', values.description)
      payload.append('brand', values.brand)
      payload.append('category', values.categories[0] || '')
      payload.append('categories', JSON.stringify(values.categories))
      payload.append('features', values.features)
      payload.append('price', String(values.price))
      payload.append('stock', String(values.stock))
      if (imageMode === 'url' && values.image_url) payload.append('image_url', values.image_url)
      if (imageMode === 'upload' && image) payload.append('image', image)
      return api.post('/products/', payload)
    },
    onMutate: async ({ product, submission }) => {
      const productsKey = ['admin', 'products'] as const
      if (!product) return { productsKey, previousList: queryClient.getQueryData<Paginated<Product>>(productsKey) }
      await queryClient.cancelQueries({ queryKey: productsKey })
      await queryClient.cancelQueries({ queryKey: ['product', product.id] })
      const previousList = queryClient.getQueryData<Paginated<Product>>(productsKey)
      const previousProduct = queryClient.getQueryData<Product>(['product', product.id])
      const optimisticProduct = {
        ...product,
        ...submission.values,
        brand: submission.values.brand || null,
        category: submission.values.categories[0] || null,
        categories: submission.values.categories,
        feature_details: null,
        specifications: {},
        features: submission.values.features || null,
        image_url: submission.imageMode === 'url'
          ? submission.values.image_url || null
          : product.image_url,
      }
      queryClient.setQueryData<Paginated<Product>>(productsKey, (current) => current && ({
        ...current,
        items: current.items.map((item) => item.id === product.id ? optimisticProduct : item),
      }))
      queryClient.setQueryData(['product', product.id], optimisticProduct)
      return { productsKey, previousList, productId: product.id, previousProduct }
    },
    onError: (_error, _variables, context) => {
      if (context?.previousList) queryClient.setQueryData(context.productsKey, context.previousList)
      if (context?.previousProduct && context.productId) queryClient.setQueryData(['product', context.productId], context.previousProduct)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'products'] })
      queryClient.invalidateQueries({ queryKey: ['products'] })
    },
  })
  const deleteProductMutation = useMutation<unknown, Error, number, DeleteProductContext>({
    mutationFn: (productId: number) => api.delete(`/products/${productId}`),
    onMutate: async (productId) => {
      const productsKey = ['admin', 'products'] as const
      await queryClient.cancelQueries({ queryKey: productsKey })
      const previousList = queryClient.getQueryData<Paginated<Product>>(productsKey)
      queryClient.setQueryData<Paginated<Product>>(productsKey, (current) => current && ({
        ...current,
        total: Math.max(0, current.total - 1),
        items: current.items.filter((item) => item.id !== productId),
      }))
      return { productsKey, previousList }
    },
    onError: (_error, _productId, context) => {
      if (context?.previousList) queryClient.setQueryData(context.productsKey, context.previousList)
    },
    onSettled: (_data, _error, productId) => {
      queryClient.removeQueries({ queryKey: ['product', productId] })
      queryClient.invalidateQueries({ queryKey: ['admin', 'products'] })
      queryClient.invalidateQueries({ queryKey: ['products'] })
    },
  })

  function changeSection(value: ProductSection) {
    setError('')
    setCreatingProduct(false)
    setEditingProductId(null)
    setSection(value)
  }

  function beginCreate() {
    setCreatingProduct(true)
    setEditingProductId(null)
    setError('')
  }

  function beginEdit(product: Product) {
    setCreatingProduct(false)
    setEditingProductId(product.id)
    setError('')
  }

  async function saveProduct(product: Product | null, submission: ProductEditorValues) {
    setError('')
    try {
      if (product) {
        await saveProductMutation.mutateAsync({ product, submission })
        toast.success('Product updated successfully.')
      } else {
        await saveProductMutation.mutateAsync({ product: null, submission })
        toast.success('Product created successfully.')
      }
      setEditingProductId(null)
      setCreatingProduct(false)
    } catch (requestError) {
      const message = errorMessage(requestError)
      setError(message)
      toast.error(message)
    }
  }

  async function deleteProduct(product: Product) {
    if (!window.confirm(`Remove “${product.name}” from the catalog?`)) return
    setError('')
    try {
      await deleteProductMutation.mutateAsync(product.id)
      toast.success('Product removed successfully.')
    } catch (requestError) {
      const message = errorMessage(requestError)
      setError(message)
      toast.error(message)
    }
  }

  async function cancelOrder(order: Order) {
    setBusyOrder(order.id)
    setError('')
    try {
      await orderMutation.mutateAsync({ orderId: order.id, action: 'cancel' })
      toast.success(`Order #${order.id} cancelled.`)
    } catch (requestError) {
      const message = errorMessage(requestError)
      setError(message)
      toast.error(message)
    } finally {
      setBusyOrder(null)
    }
  }

  async function advanceOrder(order: Order, status: OrderStatus) {
    setBusyOrder(order.id)
    setError('')
    try {
      await orderMutation.mutateAsync({ orderId: order.id, action: 'status', status })
      toast.success(`Order #${order.id} moved to ${status}.`)
    } catch (requestError) {
      const message = errorMessage(requestError)
      setError(message)
      toast.error(message)
    } finally {
      setBusyOrder(null)
    }
  }

  const pendingCount = orders.filter((order) => order.status === 'Pending').length
  const orderRevenue = orders.reduce((sum, order) => sum + Number(order.total_amount || 0), 0)
  const visibleOrders = orderFilter === 'All' ? orders : orders.filter((order) => order.status === orderFilter)

  return (
    <main className="admin-page">
      <div className="admin-heading">
        <div><p className="eyebrow"><span className="eyebrow-line" /> Store management</p><h1>Admin dashboard</h1><p className="admin-welcome">Signed in as {user?.name} · administrator</p></div>
        <span className="admin-role-mark"><ShieldCheck size={17} /> Admin access</span>
      </div>

      <div className="admin-metrics">
        <div><span>All orders</span><strong>{orders.length}</strong><small>Across every customer</small></div>
        <div><span>Pending</span><strong>{pendingCount}</strong><small>Awaiting fulfillment</small></div>
        <div><span>Order value</span><strong>{formatPrice(orderRevenue)}</strong><small>Recorded order totals</small></div>
        <div><span>Catalog</span><strong>{products.length}</strong><small>Products currently listed</small></div>
      </div>

      <div className="admin-toolbar">
        <div className="admin-tabs" role="tablist" aria-label="Admin sections">
          <button role="tab" aria-selected={section === 'orders'} className={section === 'orders' ? 'selected' : ''} onClick={() => changeSection('orders')}><ClipboardList size={15} /> All orders</button>
          <button role="tab" aria-selected={section === 'products'} className={section === 'products' ? 'selected' : ''} onClick={() => changeSection('products')}><PackagePlus size={15} /> Products</button>
        </div>
        <div className="admin-actions">
          <Link className="text-link" to="/admin/chats">Customer chats <MessageCircle size={14} /></Link>
          <Link className="text-link" to="/jobs">Background jobs <ArrowRight size={14} /></Link>
          {section === 'products' && <Button size="sm" onClick={beginCreate}><PackagePlus size={14} /> Add product</Button>}
          <Button variant="outline" size="sm" aria-label="Refresh admin data" title="Refresh" onClick={() => { ordersQuery.refetch(); productsQuery.refetch() }}><RefreshCw size={14} /> Refresh</Button>
        </div>
      </div>

      {section === 'products' && <CsvImportPanel />}

      {(error || (ordersQuery.error && errorMessage(ordersQuery.error)) || (productsQuery.error && errorMessage(productsQuery.error))) && <div className="notice notice-error" role="alert">{error || errorMessage(ordersQuery.error || productsQuery.error)}</div>}

      {section === 'products' && creatingProduct && (
        <section className="admin-create-product" aria-labelledby="create-product-title">
          <div className="admin-form-title"><div><p className="eyebrow"><span className="eyebrow-line" /> New catalog item</p><h2 id="create-product-title">Add a product</h2></div><button className="icon-button" type="button" aria-label="Close product form" onClick={() => setCreatingProduct(false)}><X size={17} /></button></div>
          <AdminProductEditor product={null} saving={saveProductMutation.isPending} onCancel={() => setCreatingProduct(false)} onSave={(submission) => saveProduct(null, submission)} />
        </section>
      )}

      {loading ? <div className="route-loading admin-loading">Loading {section}...</div> : section === 'orders' ? (
        orders.length ? <>
          <div className="admin-order-filters" role="group" aria-label="Filter orders by status">
            <button type="button" aria-pressed={orderFilter === 'All'} className={orderFilter === 'All' ? 'selected' : ''} onClick={() => setOrderFilter('All')}>All orders <span>{orders.length}</span></button>
            {orderStatuses.map((status) => {
              const count = orders.filter((order) => order.status === status).length
              return <button type="button" aria-pressed={orderFilter === status} className={orderFilter === status ? 'selected' : ''} key={status} onClick={() => setOrderFilter(status)}>{status} <span>{count}</span></button>
            })}
          </div>
          {visibleOrders.length ? <section className="admin-table-wrap" aria-label={`${orderFilter === 'All' ? 'All' : orderFilter} orders`}>
            <table className="admin-table">
              <thead><tr><th>Order</th><th>Customer</th><th>Items</th><th>Total</th><th>Payment</th><th>Date</th><th>Status</th><th>Action</th></tr></thead>
              <tbody>
                {visibleOrders.map((order) => {
                  const nextStep = nextOrderStep[order.status]
                  return <tr key={order.id}>
                    <td className="admin-order-id">#{String(order.id).padStart(5, '0')}</td>
                    <td><div className="admin-customer-cell"><strong>{order.customer?.name || `Customer #${order.user_id}`}</strong>{order.customer?.email && <small>{order.customer.email}</small>}{order.shipping_address && <small>Ship to {order.shipping_address.address_line}, {order.shipping_address.city}</small>}</div></td>
                    <td>{order.items?.map((item) => `${item.quantity} × ${item.product_name || `Product #${item.product_id}`}`).join(', ') || 'No items'}</td>
                    <td>{formatPrice(order.total_amount)}</td>
                    <td><div className="admin-payment-cell"><strong>{formatPaymentMethod(order.payment_method)}</strong><small>Demo only · not processed</small></div></td>
                    <td>{new Date(order.created_at).toLocaleDateString()}</td>
                    <td><span className={`admin-status ${order.status.toLowerCase().replaceAll(' ', '-')}`}>{order.status}</span></td>
                    <td>{nextStep || order.status === 'Pending' ? <div className="admin-order-actions">
                      {nextStep && <Button className="complete-order-button" variant="outline" size="sm" disabled={busyOrder === order.id} onClick={() => advanceOrder(order, nextStep.status)}>{nextStep.status === 'Completed' ? <CheckCircle2 size={13} /> : <ArrowRight size={13} />}{busyOrder === order.id ? 'Updating...' : nextStep.label}</Button>}
                      {order.status === 'Pending' && <Button variant="outline" size="sm" disabled={busyOrder === order.id} onClick={() => cancelOrder(order)}>{busyOrder === order.id ? 'Updating...' : 'Cancel'}</Button>}
                    </div> : <span className="admin-muted">—</span>}</td>
                  </tr>
                })}
              </tbody>
            </table>
          </section> : <div className="admin-empty">No {orderFilter.toLowerCase()} orders.</div>}
        </> : <div className="admin-empty">There are no orders yet.</div>
      ) : (
        <section className="admin-product-catalog" aria-label="Product catalog management">
          <div className="admin-catalog-heading"><div><p className="eyebrow"><span className="eyebrow-line" /> Manage your collection</p><h2>{products.length} products</h2></div></div>
          {products.length ? <div className="admin-product-grid">{products.map((product) => (
            <article className={`admin-product-card${editingProductId === product.id ? ' is-editing' : ''}`} key={product.id}>
              {editingProductId === product.id ? (
                <div className="admin-inline-editor">
                  <div className="admin-inline-editor-heading"><div><p className="eyebrow">Editing product</p><h3>{product.name}</h3></div><button className="icon-button" type="button" aria-label={`Close ${product.name} editor`} onClick={() => setEditingProductId(null)}><X size={16} /></button></div>
                  <AdminProductEditor product={product} saving={saveProductMutation.isPending} onCancel={() => setEditingProductId(null)} onSave={(submission) => saveProduct(product, submission)} />
                </div>
              ) : (
                <>
                  <div className="admin-card-image"><ProductImage product={product} className="admin-product-card-image" /><span className={`admin-stock-chip${product.stock < 1 ? ' is-empty' : ''}`}>{product.stock > 0 ? `${product.stock} in stock` : 'Out of stock'}</span></div>
                  <div className="admin-product-card-content">
                    <div className="admin-product-card-title"><div><p className="admin-product-category">Product #{product.id}</p><h3>{product.name}</h3></div><strong>{formatPrice(product.price)}</strong></div>
                    <p className="admin-product-description">{product.description || 'A considered everyday essential.'}</p>
                    <div className="admin-product-card-actions"><Button variant="outline" size="sm" aria-label={`Edit ${product.name}`} onClick={() => beginEdit(product)}><Pencil size={14} /> Edit product</Button><Button variant="outline" size="sm" aria-label={`Delete ${product.name}`} onClick={() => deleteProduct(product)}><Trash2 size={14} /><span className="sr-only">Delete</span></Button></div>
                  </div>
                </>
              )}
            </article>
          ))}</div> : <div className="admin-empty">No products in the catalog yet.</div>}
        </section>
      )}
    </main>
  )
}