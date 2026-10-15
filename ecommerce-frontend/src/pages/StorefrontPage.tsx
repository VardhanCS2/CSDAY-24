import { memo, useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  Armchair,
  ArrowDown,
  ArrowRight,
  ArrowUpDown,
  Bike,
  BookOpen,
  CookingPot,
  Footprints,
  Grid2X2,
  Laptop,
  Puzzle,
  Search,
  Shirt,
  ShoppingBag,
  ShoppingBasket,
  Shapes,
  SlidersHorizontal,
  Sparkles,
  Watch,
  type LucideIcon,
} from 'lucide-react'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import { useAuth } from '@/hooks/useAuth'
import { useCartActions } from '@/hooks/use-cart'
import { useDebouncedValue } from '@/hooks/use-debounced-value'
import { useIntersectionObserver } from '@/hooks/use-intersection-observer'
import { useProductCategories, useProducts } from '@/hooks/use-products'
import { ProductImage } from '@/components/ProductImage'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { formatPrice } from '@/lib/utils'
import { PRODUCT_CATEGORIES } from '@/lib/product-categories'
import type { Product } from '@/types/models'

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  laptop: Laptop,
  footprints: Footprints,
  shirt: Shirt,
  'cooking-pot': CookingPot,
  armchair: Armchair,
  sparkles: Sparkles,
  bike: Bike,
  'book-open': BookOpen,
  puzzle: Puzzle,
  'shopping-basket': ShoppingBasket,
  watch: Watch,
  shapes: Shapes,
}
interface ProductCardProps {
  product: Product
  adding: boolean
  onAdd: (product: Product) => void
}

const ProductCard = memo(function ProductCard({ product, adding, onAdd }: ProductCardProps) {
  return (
    <article className="product-card">
      <Link to={`/product/${product.id}`} className="product-image-link" aria-label={`View ${product.name}`}>
        <ProductImage product={product} className="product-image" />
        <Badge className={product.stock > 0 ? 'stock-badge' : 'stock-badge sold-out'}>{product.stock > 0 ? 'In stock' : 'Sold out'}</Badge>
      </Link>
      <div className="product-info"><div><Link to={`/product/${product.id}`} className="product-name">{product.name}</Link><p className="product-subtitle">{product.description || 'A considered everyday essential.'}</p></div><strong>{formatPrice(product.price)}</strong></div>
      <Button className="product-add" variant="outline" disabled={product.stock < 1 || adding} onClick={() => onAdd(product)}>
        <ShoppingBag size={15} /> {adding ? 'Adding...' : product.stock < 1 ? 'Unavailable' : 'Add to bag'}
      </Button>
    </article>
  )
})

export function StorefrontPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [searchFocused, setSearchFocused] = useState(false)
  const [minPrice, setMinPrice] = useState('')
  const [maxPrice, setMaxPrice] = useState('')
  const [stock, setStock] = useState<'all' | 'in' | 'out'>('all')
  const [sort, setSort] = useState<'recommended' | 'price-low' | 'price-high' | 'name'>('recommended')
  const [searchMode, setSearchMode] = useState<'hybrid' | 'semantic'>('hybrid')
  const [addingId, setAddingId] = useState<number | null>(null)
  const debouncedSearch = useDebouncedValue(search.trim())
  const filters = useMemo(() => ({
    ...(debouncedSearch ? { search: debouncedSearch } : {}),
    ...(debouncedSearch ? { search_mode: searchMode } : {}),
    ...(category ? { category } : {}),
    ...(minPrice !== '' ? { min_price: minPrice } : {}),
    ...(maxPrice !== '' ? { max_price: maxPrice } : {}),
    ...(stock !== 'all' ? { stock_available: stock === 'in' } : {}),
  }), [debouncedSearch, minPrice, maxPrice, stock, searchMode, category])
  const productsQuery = useProducts(filters)
  const categoriesQuery = useProductCategories()
  const { add } = useCartActions()
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = productsQuery
  const addToCart = add.mutateAsync
  const loadMoreRef = useRef<HTMLDivElement>(null)
  const isLoadMoreVisible = useIntersectionObserver(loadMoreRef, { rootMargin: '400px' })
  const products = useMemo(() => productsQuery.data?.pages.flatMap((page) => page.items) || [], [productsQuery.data])
  const sortedProducts = useMemo(() => [...products].sort((first, second) => {
    if (sort === 'price-low') return first.price - second.price
    if (sort === 'price-high') return second.price - first.price
    if (sort === 'name') return first.name.localeCompare(second.name)
    return 0
  }), [products, sort])
  const total = productsQuery.data?.pages[0]?.total || 0
  const error = productsQuery.error ? errorMessage(productsQuery.error) : ''
  const suggestions = sortedProducts.slice(0, 5)

  useEffect(() => {
    if (isLoadMoreVisible && hasNextPage && !isFetchingNextPage) {
      fetchNextPage()
    }
  }, [isLoadMoreVisible, hasNextPage, isFetchingNextPage, fetchNextPage])

  const addToBag = useCallback(async (product: Product) => {
    if (!user) {
      navigate('/login', { state: { from: { pathname: `/product/${product.id}` } } })
      return
    }
    setAddingId(product.id)
    try {
      await addToCart({ product, quantity: 1 })
      toast.success(`${product.name} added to your bag.`)
    } catch (requestError) {
      toast.error(errorMessage(requestError))
    } finally {
      setAddingId(null)
    }
  }, [addToCart, navigate, user])

  function updateFilter<T extends string>(setter: Dispatch<SetStateAction<T>>, value: T) {
    setter(value)
  }

  return (
    <main>
      <section className="hero-band">
        <div className="hero-copy">
          <p className="eyebrow"><span className="eyebrow-line" /> The considered collection</p>
          <h1>Everyday things.<br /><em>Made a little better.</em></h1>
          <p className="hero-description">Objects for slower mornings, thoughtful gifting, and the small rituals that make a day.</p>
          <a className="hero-link" href="#shop">Explore the collection <ArrowDown size={16} /></a>
          <div className="hero-caption"><span>01 / 03</span><span>Objects with purpose</span></div>
        </div>
        <div className="hero-image-wrap">
          <img src="https://images.unsplash.com/photo-1490312278390-ab64016e0aa9?auto=format&fit=crop&w=1000&q=80" srcSet="https://images.unsplash.com/photo-1490312278390-ab64016e0aa9?auto=format&fit=crop&w=640&q=80 640w, https://images.unsplash.com/photo-1490312278390-ab64016e0aa9?auto=format&fit=crop&w=1000&q=80 1000w, https://images.unsplash.com/photo-1490312278390-ab64016e0aa9?auto=format&fit=crop&w=1500&q=80 1500w" sizes="(max-width: 800px) 100vw, 52vw" alt="Thoughtfully arranged home and lifestyle objects" width="1500" height="1000" decoding="async" fetchPriority="high" />
          <div className="hero-image-note"><span>THE DAILY EDIT</span><b>Less, but considered.</b></div>
          <span className="hero-side-label">COMMON GOODS · VOL. 01</span>
        </div>
      </section>

      <section className="shop-section" id="shop">
        <div className="section-heading">
          <div><p className="eyebrow"><span className="eyebrow-line" /> The collection</p><h2>Find your everyday favorite.</h2></div>
          <span className="result-total">{total} {total === 1 ? 'piece' : 'pieces'}</span>
        </div>
        <nav className="category-strip" aria-label="Shop by category">
          <div className="category-scroll" role="group" aria-label="Product categories">
            <button
              type="button"
              className={`category-option${category ? '' : ' is-selected'}`}
              aria-pressed={!category}
              onClick={() => setCategory('')}
            >
              <span className="category-icon"><Grid2X2 size={18} aria-hidden="true" /></span>
              <span>All products</span>
            </button>
            {(categoriesQuery.data?.length ? categoriesQuery.data : PRODUCT_CATEGORIES).map((item) => {
              const Icon = CATEGORY_ICONS[item.icon] ?? Shapes
              return (
                <button
                  type="button"
                  key={item.name}
                  className={`category-option${category === item.name ? ' is-selected' : ''}`}
                  aria-pressed={category === item.name}
                  onClick={() => setCategory(item.name)}
                >
                  <span className="category-icon"><Icon size={18} aria-hidden="true" /></span>
                  <span>{item.name}</span>
                </button>
              )
            })}
          </div>
        </nav>
        <div className="filter-bar">
          <div className="search-box">
            <label className="search-field"><Search size={17} /><Input aria-label="Search products" placeholder="Search by product, material, or style" value={search} onFocus={() => setSearchFocused(true)} onBlur={() => window.setTimeout(() => setSearchFocused(false), 120)} onKeyDown={(event) => { if (event.key === 'Escape') setSearchFocused(false) }} onChange={(event) => updateFilter(setSearch, event.target.value)} autoComplete="off" /><kbd>⌕</kbd></label>
            {searchFocused && debouncedSearch && (
              <div className="search-suggestions" role="listbox" aria-label="Matching products">
                {productsQuery.isFetching && !suggestions.length ? <p className="search-suggestion-empty">Searching the collection…</p> : suggestions.length ? suggestions.map((product) => (
                  <Link key={product.id} to={`/product/${product.id}`} className="search-suggestion" role="option" aria-selected="false" onClick={() => setSearchFocused(false)}>
                    <ProductImage product={product} className="search-suggestion-image" />
                    <span><strong>{product.name}</strong><small>{product.description || 'Everyday essential'}</small></span>
                    <b>{formatPrice(product.price)}</b>
                  </Link>
                )) : <p className="search-suggestion-empty">No close matches yet. Try another spelling.</p>}
              </div>
            )}
          </div>
          <div className="filter-controls">
            <label className="compact-filter"><span>Price</span><Input aria-label="Minimum price" type="number" min="0" placeholder="Min" value={minPrice} onChange={(event) => updateFilter(setMinPrice, event.target.value)} /><span className="price-divider">to</span><Input aria-label="Maximum price" type="number" min="0" placeholder="Max" value={maxPrice} onChange={(event) => updateFilter(setMaxPrice, event.target.value)} /></label>
            <label className="select-filter"><SlidersHorizontal size={15} /><select aria-label="Availability" value={stock} onChange={(event) => { const value = event.target.value; if (value === 'all' || value === 'in' || value === 'out') setStock(value) }}><option value="all">Availability</option><option value="in">In stock</option><option value="out">Sold out</option></select></label>
            <label className="select-filter"><select aria-label="Search type" value={searchMode} onChange={(event) => { const value = event.target.value; if (value === 'hybrid' || value === 'semantic') setSearchMode(value) }}><option value="hybrid">Keyword search</option><option value="semantic">AI semantic search</option></select></label>
            <label className="select-filter sort-filter"><ArrowUpDown size={15} /><select aria-label="Sort products" value={sort} onChange={(event) => { const value = event.target.value; if (value === 'recommended' || value === 'price-low' || value === 'price-high' || value === 'name') setSort(value) }}><option value="recommended">Featured</option><option value="price-low">Price: low to high</option><option value="price-high">Price: high to low</option><option value="name">Name: A to Z</option></select></label>
          </div>
        </div>

        {error && !products.length && <div className="notice notice-error" role="alert">{error}</div>}
        {productsQuery.isPending ? <div className="product-grid" aria-label="Loading products">{Array.from({ length: 8 }, (_, index) => <div className="product-skeleton" key={index} />)}</div> : error && !products.length ? (
          <div className="empty-state"><p className="eyebrow">Connection issue</p><h3>We couldn’t reach the collection.</h3><p>{error}</p><Button onClick={() => productsQuery.refetch()}>Try again</Button></div>
        ) : sortedProducts.length ? (
          <div className="product-grid">
            {sortedProducts.map((product) => <ProductCard key={product.id} product={product} adding={addingId === product.id} onAdd={addToBag} />)}
          </div>
        ) : (
          <div className="empty-state"><p className="eyebrow">Nothing here just yet</p><h3>No pieces match those filters.</h3><p>Try a different search or reset your price range.</p><Button variant="outline" onClick={() => { setSearch(''); setCategory(''); setMinPrice(''); setMaxPrice(''); setStock('all') }}>Clear filters <ArrowRight size={15} /></Button></div>
        )}

        {hasNextPage && <div className="pagination" ref={loadMoreRef}><Button variant="outline" size="sm" disabled={isFetchingNextPage} onClick={() => fetchNextPage()}>{isFetchingNextPage ? 'Loading more...' : 'Load more'} <ArrowRight size={14} /></Button></div>}
      </section>
      <section className="promise-strip"><span>Thoughtfully sourced</span><i /><span>Made to be kept</span><i /><span>Here for the everyday</span></section>
    </main>
  )
}