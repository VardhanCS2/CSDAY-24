import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ImagePlus, Link2, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { ProductImage } from '@/components/ProductImage'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { errorMessage } from '@/api/client'
import { productSchema } from '@/lib/validation'
import type { Product } from '@/types/models'
import type { z } from 'zod'

type ProductValues = z.infer<typeof productSchema>

export interface ProductEditorValues {
  values: ProductValues
  image: File | null
  imageMode: 'url' | 'upload'
}

interface AdminProductEditorProps {
  product: Product | null
  saving: boolean
  onCancel: () => void
  onSave: (submission: ProductEditorValues) => Promise<void>
}

export function AdminProductEditor({ product, saving, onCancel, onSave }: AdminProductEditorProps) {
  const [name, setName] = useState(product?.name ?? '')
  const [description, setDescription] = useState(product?.description ?? '')
  const [price, setPrice] = useState(product ? String(product.price) : '')
  const [stock, setStock] = useState(product ? String(product.stock) : '')
  const [imageUrl, setImageUrl] = useState(product?.image_url?.startsWith('http') ? product.image_url : '')
  const [imageMode, setImageMode] = useState<'url' | 'upload'>(product?.image_url?.startsWith('http') ? 'url' : 'upload')
  const [image, setImage] = useState<File | null>(null)
  const [imageError, setImageError] = useState('')
  const [previewStatus, setPreviewStatus] = useState<'pending' | 'ready' | 'failed'>('pending')
  const uploadPreviewRef = useRef<HTMLImageElement>(null)
  const urlIsValid = productSchema.shape.image_url.safeParse(imageUrl).success

  useEffect(() => {
    if (!image) return
    const objectUrl = URL.createObjectURL(image)
    if (uploadPreviewRef.current) uploadPreviewRef.current.src = objectUrl
    return () => URL.revokeObjectURL(objectUrl)
  }, [image])

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setImageError('')
    const parsed = productSchema.safeParse({ name, description, price, stock, image_url: imageUrl })
    if (!parsed.success) {
      toast.error(parsed.error.issues[0]?.message ?? 'Check the product details.')
      return
    }
    if (imageMode === 'url' && imageUrl && previewStatus !== 'ready') {
      const message = previewStatus === 'failed'
        ? 'This image URL could not be loaded. Check the URL or choose another image.'
        : 'Wait for the image preview to finish loading before saving.'
      setImageError(message)
      toast.error(message)
      return
    }
    void onSave({
      values: parsed.data,
      image: imageMode === 'upload' ? image : null,
      imageMode,
    }).catch((error: unknown) => {
      const message = errorMessage(error)
      setImageError(message)
      toast.error(message)
    })
  }

  const preview = imageMode === 'url'
    ? imageUrl
      ? <img className="admin-image-preview" src={imageUrl} alt="Product image preview" loading="lazy" decoding="async" onLoad={() => setPreviewStatus('ready')} onError={() => setPreviewStatus('failed')} />
      : null
    : image
      ? <img className="admin-image-preview" ref={uploadPreviewRef} alt="Selected product image preview" loading="lazy" decoding="async" onLoad={() => setPreviewStatus('ready')} onError={() => setPreviewStatus('failed')} />
      : product?.image_url
        ? <ProductImage product={product} className="admin-image-preview" />
        : null

  return (
    <form className="admin-product-editor" onSubmit={submit}>
      <div className="admin-editor-fields">
        <label className="form-field"><span>Product name</span><Input value={name} onChange={(event) => setName(event.target.value)} required maxLength={100} /></label>
        <label className="form-field"><span>Price</span><Input type="number" min="0" step="0.01" value={price} onChange={(event) => setPrice(event.target.value)} required /></label>
        <label className="form-field"><span>Stock</span><Input type="number" min="0" step="1" value={stock} onChange={(event) => setStock(event.target.value)} required /></label>
        <label className="form-field admin-editor-description"><span>Description</span><Input value={description} onChange={(event) => setDescription(event.target.value)} maxLength={2000} /></label>
      </div>
      <fieldset className="admin-image-picker">
        <legend>Product image</legend>
        <div className="admin-image-options" role="group" aria-label="Product image source">
          <button type="button" className={imageMode === 'url' ? 'selected' : ''} aria-pressed={imageMode === 'url'} onClick={() => { setImageMode('url'); setPreviewStatus('pending'); setImageError('') }}><Link2 size={14} /> Image URL</button>
          <button type="button" className={imageMode === 'upload' ? 'selected' : ''} aria-pressed={imageMode === 'upload'} onClick={() => { setImageMode('upload'); setPreviewStatus('pending'); setImageError('') }}><Upload size={14} /> Upload image</button>
        </div>
        <div className="admin-image-preview-row">
          {imageMode === 'url' ? (
            <label className="form-field"><span>Image URL</span><Input type="url" inputMode="url" placeholder="https://example.com/product-image.jpg" value={imageUrl} aria-invalid={Boolean(imageUrl && !urlIsValid)} onChange={(event) => { setImageUrl(event.target.value); setPreviewStatus('pending'); setImageError('') }} /></label>
          ) : (
            <label className="form-field"><span>{product?.image_url ? 'Replace image' : 'Choose image file'}</span><span className="file-input-wrap"><ImagePlus size={15} /><input type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => {
              const file = event.target.files?.[0] ?? null
              if (file && (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 5 * 1024 * 1024)) {
                setImageError('Choose a JPG, PNG, or WEBP image up to 5 MB.')
                event.target.value = ''
                return
              }
              setImage(file)
              setPreviewStatus('pending')
              setImageError('')
            }} /><small>{image?.name ?? (product?.image_url ? 'Keep current image or choose a replacement' : 'JPG, PNG, or WEBP · up to 5 MB')}</small></span></label>
          )}
          <div className="admin-image-preview-box" aria-label="Image preview">
            {preview || <div className="admin-image-preview-empty"><ImagePlus size={21} /><span>{imageMode === 'url' ? (imageUrl ? 'Loading preview…' : 'Paste an image URL') : 'Image preview'}</span></div>}
          </div>
        </div>
        {imageMode === 'url' && imageUrl && !urlIsValid && <p className="form-message error-text">Enter a valid HTTP or HTTPS image URL.</p>}
        {imageError && <p className="form-message error-text" role="alert">{imageError}</p>}
      </fieldset>
      <div className="admin-form-actions">
        <Button type="button" variant="outline" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={saving || (imageMode === 'url' && Boolean(imageUrl) && (!urlIsValid || previewStatus !== 'ready'))}>{saving ? 'Saving...' : product ? 'Save product' : 'Create product'}</Button>
      </div>
    </form>
  )
}
