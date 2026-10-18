# Phase 16 (§78): production image for the Next.js frontend, using
# `output: "standalone"` (next.config.ts) for a minimal runtime image.

FROM node:22-slim AS build
WORKDIR /app

ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production

USER node

# This is a monorepo (turbopack root = repo root, see next.config.ts), so
# Next.js nests the traced standalone output under apps/web/ instead of
# putting server.js at the output root -- copy the whole nested tree and
# point CMD/static/public copies at that same nested path.
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./app/.next/static
COPY --from=build --chown=node:node /app/public ./app/public

EXPOSE 3000
ENV PORT=3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "require('http').get('http://localhost:3000/', r => process.exit(r.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))"

CMD SERVER=$(find /app -type f -name server.js ! -path '*/node_modules/*' | head -n 1) && echo "Starting $SERVER" && exec node "$SERVER"
