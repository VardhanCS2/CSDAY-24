# ==========================================
# Stage 1: Build the frontend SPA bundle
# ==========================================
FROM node:22-alpine AS builder

WORKDIR /app

# Install dependencies using clean install
COPY package.json package-lock.json ./
RUN npm ci

# Copy source code and build production assets
COPY . .
RUN npm run build

# ==========================================
# Stage 2: Serve with lightweight Nginx
# ==========================================
FROM nginx:alpine AS runner

# Remove default nginx static assets
RUN rm -rf /usr/share/nginx/html/*

# Copy compiled static assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy optimized reverse-proxy & SPA configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Health check to verify web server responsiveness
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/healthz || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
