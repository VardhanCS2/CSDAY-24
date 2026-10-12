import type { ImgHTMLAttributes } from 'react'
import type { Product } from '@/types/models'

const productImages: Array<[RegExp, string]> = [
  [/\b(bottle|flask|water bottle|thermos)\b/i, 'photo-1602143407151-7111542de6e8'],
  [/\b(bag|tote|purse|handbag|backpack)\b/i, 'photo-1548036328-c9fa89d128fa'],
  [/\b(watch|timepiece)\b/i, 'photo-1523275335684-37898b6baf30'],
  [/\b(headphone|earbud|speaker|audio)\b/i, 'photo-1505740420928-5e560c06d30e'],
  [/\b(candle|wax|fragrance|scent)\b/i, 'photo-1603006905003-be475563bc59'],
  [/\b(chair|stool|furniture|seat)\b/i, 'photo-1503602642458-232111445657'],
  [/\b(coffee maker|espresso|grinder)\b/i, 'photo-1570222094114-d054a817e56b'],
  [/\b(mug|cup|glass|tumbler|drinkware)\b/i, 'photo-1514228742587-6b1558fcca3d'],
  [/\b(shoe|sneaker|boot|sandal)\b/i, 'photo-1542291026-7eec264c27ff'],
  [/\b(book|journal|notebook|paper)\b/i, 'photo-1544947950-fa07a98d237f'],
  [/\b(lamp|light|lighting)\b/i, 'photo-1507473885765-e6ed057f782c'],
  [/\b(vase|pottery|ceramic|bowl|basket)\b/i, 'photo-1578749556568-bc2c40e68b61'],
]

interface ProductImageProps extends Omit<ImgHTMLAttributes<HTMLImageElement>, 'src' | 'alt' | 'onError'> {
  product: Pick<Product, 'id' | 'name' | 'image_url'>
}

export function ProductImage({ product, className = '', loading = 'lazy', fetchPriority, sizes = '(max-width: 700px) 90vw, (max-width: 1100px) 45vw, 32vw' }: ProductImageProps) {
  const remoteImage = typeof product.image_url === 'string' && /^https?:\/\//.test(product.image_url)
    ? product.image_url
    : null
  const storedPath = typeof product.image_url === 'string' && !remoteImage
    ? product.image_url.replace(/^\/?app\//, '').replace(/^\//, '')
    : null
  const imageId = productImages.find(([pattern]) => pattern.test(product.name))?.[1] ?? 'photo-1490312278390-ab64016e0aa9'
  const fallbackImage = `https://images.unsplash.com/${imageId}?auto=format&fit=max&w=900&q=80`
  const fallbackSrcSet = [320, 640, 900]
    .map((width) => `https://images.unsplash.com/${imageId}?auto=format&fit=max&w=${width}&q=80 ${width}w`)
    .join(', ')
  const imageUrl = remoteImage || (storedPath ? `/api/${storedPath}` : fallbackImage)

  return (
    <img
      className={className}
      src={imageUrl}
      srcSet={!remoteImage && !storedPath ? fallbackSrcSet : undefined}
      sizes={sizes}
      alt={product.name}
      width="900"
      height="1012"
      loading={loading}
      fetchPriority={fetchPriority}
      decoding="async"
      onError={(event) => { event.currentTarget.src = fallbackImage }}
    />
  )
}