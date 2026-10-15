import { useEffect, useRef, useState, type FormEvent } from 'react'
import axios from 'axios'
import { ImagePlus, Link2, Sparkles, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { ProductImage } from '@/components/ProductImage'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api, errorMessage, responseData } from '@/api/client'
import { PRODUCT_CATEGORIES } from '@/lib/product-categories'
import { productSchema } from '@/lib/validation'
import type { BackgroundJob, Product } from '@/types/models'
import type { z } from 'zod'

type ProductValues = z.infer<typeof productSchema>

const AI_JOB_POLL_INTERVAL_MS = 750
const AI_JOB_MAX_POLL_ATTEMPTS = 80

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
  const [brand, setBrand] = useState(product?.brand ?? '')
  const [categories, setCategories] = useState<string[]>(product?.categories ?? [])
  const [features, setFeatures] = useState(product?.features || product?.feature_details || '')
  const [price, setPrice] = useState(product ? String(product.price) : '')
  const [stock, setStock] = useState(product ? String(product.stock) : '')
  const [imageUrl, setImageUrl] = useState(product?.image_url?.startsWith('http') ? product.image_url : '')
  const [imageMode, setImageMode] = useState<'url' | 'upload'>(product?.image_url?.startsWith('http') ? 'url' : 'upload')
  const [image, setImage] = useState<File | null>(null)
  const [imageError, setImageError] = useState('')
  const [contentError, setContentError] = useState('')
  const [generatingContent, setGeneratingContent] = useState(false)
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
    setContentError('')
    const parsed = productSchema.safeParse({
      name, description, brand, categories, features, price, stock, image_url: imageUrl,
    })
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

  async function generateContent() {
    const numericPrice = Number(price)
    if (!name.trim() || !Number.isFinite(numericPrice) || numericPrice < 0) {
      const message = 'Enter a product name and valid price before generating product content.'
      setContentError(message)
      toast.error(message)
      return
    }
    if (
      (description.trim() || features.trim())
      && !window.confirm('Replace the current description and features with a new draft?')
    ) return

    setGeneratingContent(true)
    setContentError('')
    try {
      const response = await api.post('/ai/products/generate-content/jobs', {
        name: name.trim(),
        price: numericPrice,
        stock: Number(stock) || 0,
        brand: brand.trim() || null,
        category: categories.join(', ') || null,
        features: features.trim() || null,
        existing_description: description.trim() || null,
      })
      const queuedJob = responseData<{ id: string }>(response)
      let result: {
        description: string
        features: string
        generation_mode?: 'ai' | 'source_fallback'
      } | null = null
      for (let attempt = 0; attempt < AI_JOB_MAX_POLL_ATTEMPTS; attempt += 1) {
        if (attempt > 0) {
          await new Promise((resolve) => window.setTimeout(resolve, AI_JOB_POLL_INTERVAL_MS))
        }
        const job = responseData<BackgroundJob>(
          await api.get(`/jobs/${encodeURIComponent(queuedJob.id)}`),
        )
        if (job.status === 'failed') {
          throw new Error(job.error || 'AI product content generation failed.')
        }
        if (job.status === 'completed') {
          if (
            typeof job.result?.description !== 'string'
            || typeof job.result.features !== 'string'
          ) {
            throw new Error('The AI job completed without valid product content.')
          }
          const generationMode = job.result.generation_mode
          result = {
            description: job.result.description,
            features: job.result.features,
            ...(generationMode === 'ai' || generationMode === 'source_fallback'
              ? { generation_mode: generationMode }
              : {}),
          }
          break
        }
      }
      if (!result) {
        throw new Error('Generation is still running. Check the Background Jobs page for its status.')
      }
      setDescription(result.description)
      setFeatures(result.features)
      toast.success(
        result.generation_mode === 'source_fallback'
          ? 'AI providers are unavailable. A draft using only your supplied details is ready to review.'
          : 'Description and features generated. Review and edit before saving.',
      )
    } catch (error) {
      const message = axios.isAxiosError(error) && ['ECONNABORTED', 'ETIMEDOUT'].includes(error.code ?? '')
        ? 'Generation took too long. Please try again; the product details are still in the form.'
        : errorMessage(error)
      setContentError(message)
      toast.error(message)
    } finally {
      setGeneratingContent(false)
    }
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
        <label className="form-field"><span>Brand</span><Input value={brand} onChange={(event) => setBrand(event.target.value)} maxLength={100} /></label>
        <fieldset className="form-field admin-category-picker">
          <legend>Categories <span>(select up to 3 manually)</span></legend>
          <div className="admin-category-options">
            {PRODUCT_CATEGORIES.map((item) => {
              const selected = categories.includes(item.name)
              return (
                <label key={item.name} className={`admin-category-option${selected ? ' is-selected' : ''}`}>
                  <input
                    type="checkbox"
                    checked={selected}
                    disabled={!selected && categories.length >= 3}
                    onChange={(event) => setCategories((current) => event.target.checked
                      ? [...current, item.name]
                      : current.filter((categoryName) => categoryName !== item.name))}
                  />
                  <span>{item.name}</span>
                </label>
              )
            })}
          </div>
          {categories.length >= 3 && <small className="form-hint">You can select up to three categories.</small>}
        </fieldset>
        <label className="form-field"><span>Price</span><Input type="number" min="0" step="0.01" value={price} onChange={(event) => setPrice(event.target.value)} required /></label>
        <label className="form-field"><span>Stock</span><Input type="number" min="0" step="1" value={stock} onChange={(event) => setStock(event.target.value)} required /></label>
        <div className="form-field admin-editor-description">
          <label htmlFor="admin-product-description">Description</label>
          <textarea id="admin-product-description" className="ui-input admin-textarea" value={description} onChange={(event) => setDescription(event.target.value)} maxLength={2000} />
          <label htmlFor="admin-product-features">Features</label>
          <textarea id="admin-product-features" className="ui-input admin-textarea" value={features} onChange={(event) => setFeatures(event.target.value)} maxLength={4000} placeholder="Add product details, preferably one detail per line" />
          <Button type="button" variant="outline" size="sm" onClick={() => void generateContent()} disabled={generatingContent || saving || !name.trim() || !price}>
            <Sparkles size={14} /> {generatingContent ? 'Generating...' : 'AI Generate Description & Features'}
          </Button>
          {contentError && <p className="form-message error-text" role="alert">{contentError}</p>}
        </div>
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
