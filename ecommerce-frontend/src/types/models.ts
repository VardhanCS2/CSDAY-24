export interface User {
  id: number
  name: string
  email: string
  role: 'admin' | 'user' | string
}

export interface Session {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface Product {
  id: number
  name: string
  description: string | null
  price: number
  stock: number
  image_url: string | null
  owner_id: number
  created_at: string
}

export interface CartItem {
  product_id: number
  name: string
  description: string | null
  image_url?: string | null
  price: number
  quantity: number
  total_price: number
}

export interface ShippingAddress {
  full_name: string
  email: string
  phone: string
  address_line: string
  city: string
  postal_code: string
  country: string
}

export interface OrderItem {
  id: number
  product_id: number
  product_name?: string
  quantity: number
  price: number
}

export interface Order {
  id: number
  user_id: number
  customer?: Pick<User, 'name' | 'email'> | null
  total_amount: number
  status: 'Pending' | 'Packed' | 'Shipped' | 'Out for Delivery' | 'Delivered' | 'Completed' | 'Cancelled' | string
  created_at: string
  shipping_address?: ShippingAddress | null
  payment_method?: 'card' | 'upi' | 'cash_on_delivery' | null
  items: OrderItem[]
}

export interface BackgroundJob {
  id: string
  task_type: 'invoice' | 'product_import' | string
  resource_id: number | null
  status: 'queued' | 'running' | 'completed' | 'failed' | string
  progress: number
  result: Record<string, unknown> | null
  error: string | null
  created_at: string
  updated_at: string
}

export interface ChatMessage {
  id?: number
  sender_id: number
  sender_name: string
  recipient_id: number
  recipient_name?: string
  text: string
  created_at: string
}

export interface Paginated<T> {
  page: number
  limit: number
  total: number
  items: T[]
}

export interface ApiEnvelope<T> {
  success: boolean
  message: string
  data: T
}

export interface ProductFilters {
  search?: string
  search_mode?: 'hybrid' | 'full_text' | 'fuzzy' | 'semantic'
  min_price?: string
  max_price?: string
  stock_available?: boolean
}
