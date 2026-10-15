import { z } from 'zod'
import { PRODUCT_CATEGORIES } from '@/lib/product-categories'
import type { ShippingAddress } from '@/types/models'

const emailField = z.string().trim().email('Enter a valid email address.')
const passwordField = z.string().min(8, 'Password must contain at least 8 characters.')
const registrationPasswordField = passwordField
  .regex(/\d/, 'Password must contain at least one number.')
  .regex(/[^A-Za-z0-9\s]/, 'Password must contain at least one special character.')

export const loginSchema = z.object({
  email: emailField,
  password: passwordField,
})

export const registerSchema = z.object({
  name: z.string().trim().min(2, 'Name must contain at least 2 characters.').max(100, 'Name must be 100 characters or fewer.'),
  email: emailField,
  password: registrationPasswordField,
})

export const productSchema = z.object({
  name: z.string().trim().min(1, 'Product name is required.').max(100, 'Name must be 100 characters or fewer.'),
  description: z.string().trim().max(2000, 'Description must be 2,000 characters or fewer.'),
  brand: z.string().trim().max(100, 'Brand must be 100 characters or fewer.').default(''),
  categories: z.array(z.string()).max(3, 'A product can have at most 3 categories.')
    .refine((categories) => categories.every((category) => PRODUCT_CATEGORIES.some((item) => item.name === category)),
      'Choose categories from the standard category list.')
    .default([]),
  features: z.string().trim().max(4000, 'Features must be 4,000 characters or fewer.').default(''),
  price: z.string()
    .trim()
    .min(1, 'Price is required.')
    .regex(/^\d+(\.\d{1,2})?$/, 'Enter a valid price with up to two decimal places.')
    .transform(Number)
    .pipe(z.number().finite().min(0, 'Price cannot be negative.')),
  stock: z.string()
    .trim()
    .min(1, 'Stock is required.')
    .regex(/^\d+$/, 'Stock must be a whole number.')
    .transform(Number)
    .pipe(z.number().int().min(0, 'Stock cannot be negative.')),
  image_url: z.string().trim().default('').refine((value) => {
    if (!value) return true
    try {
      const url = new URL(value)
      return (url.protocol === 'http:' || url.protocol === 'https:') && Boolean(url.hostname)
    } catch {
      return false
    }
  }, 'Enter a valid image URL beginning with http:// or https://.'),
})

export const checkoutSchema = z.object({
  full_name: z.string().trim().min(2, 'Enter your full name.').max(100),
  email: emailField,
  phone: z.string()
    .trim()
    .min(7, 'Enter a valid phone number.')
    .max(30, 'Phone number must be 30 characters or fewer.')
    .regex(/^[+()\d\s.-]+$/, 'Enter a valid phone number.')
    .regex(/\d/, 'Enter a valid phone number.'),
  address_line: z.string().trim().min(5, 'Enter your street address.').max(200),
  city: z.string().trim().min(2, 'Enter your city.').max(100),
  postal_code: z.string().trim().min(3, 'Enter your postal code.').max(20),
  country: z.string().trim().min(2, 'Enter your country.').max(100),
}) satisfies z.ZodType<ShippingAddress>

export type CheckoutValues = z.infer<typeof checkoutSchema>
