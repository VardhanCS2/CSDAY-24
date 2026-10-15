import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { ArrowUpRight, LogOut, Menu, Moon, ShoppingBag, Sun, UserRound, X } from 'lucide-react'
import { Toaster } from 'sonner'
import { useAuth } from '@/hooks/useAuth'
import { useCartStore } from '@/stores/cart-store'
import { RealtimePanel } from '@/components/RealtimePanel'
import { AiChatAssistant } from '@/components/AiChatAssistant'

const apiDocsUrl = import.meta.env.VITE_API_DOCS_URL || (
  import.meta.env.VITE_API_BASE_URL?.startsWith('http')
    ? new URL('/docs', import.meta.env.VITE_API_BASE_URL).href
    : 'http://127.0.0.1:8000/docs'
)

export function StoreLayout() {
  const { user, logout } = useAuth()
  const cartCount = useCartStore((state) => state.items.reduce((sum, item) => sum + item.quantity, 0))
  const navigate = useNavigate()
  const location = useLocation()
  const isAdminChatsPage = location.pathname === '/admin/chats'
  const [dark, setDark] = useState(() => localStorage.getItem('theme') === 'dark')
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    localStorage.setItem('theme', dark ? 'dark' : 'light')
  }, [dark])

  function signOut() {
    logout()
    navigate('/')
  }

  return (
    <div className="app-shell">
      <Toaster position="top-right" richColors closeButton theme={dark ? 'dark' : 'light'} />
      <div className="announcement">Good things, thoughtfully chosen <span>Free delivery on eligible orders</span></div>
      <header className="site-header">
        <Link to="/" className="wordmark" aria-label="Common Goods home"><span className="brand-mark">c.</span> common goods</Link>
        <button className="icon-button mobile-menu" onClick={() => setMenuOpen((open) => !open)} aria-label={menuOpen ? 'Close menu' : 'Open menu'}>
          {menuOpen ? <X size={19} /> : <Menu size={19} />}
        </button>
        <nav className={`main-nav ${menuOpen ? 'is-open' : ''}`} aria-label="Main navigation">
          <NavLink to="/" end onClick={() => setMenuOpen(false)}>Shop all</NavLink>
          {user && <NavLink to="/orders" onClick={() => setMenuOpen(false)}>Your orders</NavLink>}
          {user && <NavLink to="/jobs" onClick={() => setMenuOpen(false)}>Background jobs</NavLink>}
          {user?.role === 'admin' && <NavLink to="/admin" onClick={() => setMenuOpen(false)}>Admin</NavLink>}
        </nav>
        <div className="header-actions">
          <button className="icon-button theme-toggle" aria-label={`Switch to ${dark ? 'light' : 'dark'} mode`} title={`Switch to ${dark ? 'light' : 'dark'} mode`} onClick={() => setDark((value) => !value)}>
            {dark ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          {user ? (
            <>
              <RealtimePanel />
              <span className="account-name">Hi, {user.name.split(' ')[0]}</span>
              <button className="icon-button" onClick={signOut} aria-label="Sign out" title="Sign out"><LogOut size={18} /></button>
            </>
          ) : <Link className="icon-button" to="/login" aria-label="Sign in" title="Sign in"><UserRound size={18} /></Link>}
          <Link className="cart-link" to={user ? '/cart' : '/login'} aria-label={`Shopping bag, ${cartCount} items`}>
            <ShoppingBag size={19} /><span>Bag</span><b>{cartCount}</b>
          </Link>
        </div>
      </header>
      <Outlet />
      {!isAdminChatsPage && <AiChatAssistant />}
      <footer className="site-footer"><Link to="/" className="footer-brand">common goods</Link><span>Everyday essentials, made more considered.</span><a href={apiDocsUrl} target="_blank" rel="noreferrer">API docs <ArrowUpRight size={13} /></a></footer>
    </div>
  )
}