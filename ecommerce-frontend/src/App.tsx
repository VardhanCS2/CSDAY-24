import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from '@/context/AuthContext'
import { ProtectedRoute } from '@/components/ProtectedRoute'
import { StoreLayout } from '@/components/StoreLayout'
import { StorefrontPage } from '@/pages/StorefrontPage'
import './App.css'

const AuthPage = lazy(() => import('@/pages/AuthPage').then((module) => ({ default: module.AuthPage })))
const AdminPage = lazy(() => import('@/pages/AdminPage').then((module) => ({ default: module.AdminPage })))
const BackgroundJobsPage = lazy(() => import('@/pages/BackgroundJobsPage').then((module) => ({ default: module.BackgroundJobsPage })))
const CartPage = lazy(() => import('@/pages/CartPage').then((module) => ({ default: module.CartPage })))
const CheckoutPage = lazy(() => import('@/pages/CheckoutPage').then((module) => ({ default: module.CheckoutPage })))
const OrdersPage = lazy(() => import('@/pages/OrdersPage').then((module) => ({ default: module.OrdersPage })))
const ProductDetailPage = lazy(() => import('@/pages/ProductDetailPage').then((module) => ({ default: module.ProductDetailPage })))
export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Suspense fallback={<main className="route-loading">Loading Common Goods...</main>}>
          <Routes>
            <Route element={<StoreLayout />}>
              <Route index element={<StorefrontPage />} />
              <Route path="product/:productId" element={<ProductDetailPage />} />
              <Route path="login" element={<AuthPage mode="login" />} />
              <Route path="register" element={<AuthPage mode="register" />} />
              <Route element={<ProtectedRoute adminOnly />}>
                <Route path="admin" element={<AdminPage />} />
              </Route>
              <Route element={<ProtectedRoute />}>
                <Route path="cart" element={<CartPage />} />
                <Route path="checkout" element={<CheckoutPage />} />
                <Route path="payments" element={<CheckoutPage />} />
                <Route path="orders" element={<OrdersPage />} />
                <Route path="jobs" element={<BackgroundJobsPage />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </Suspense>
      </AuthProvider>
    </BrowserRouter>
  )
}
