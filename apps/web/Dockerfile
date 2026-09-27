# Phase 16 (§78): production image for the Next.js frontend, using
# `output: "standalone"` (next.config.ts) for a minimal runtime image.

FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production

RUN useradd --create-home --uid 1000 appuser
USER appuser

# This is a monorepo (turbopack root = repo root, see next.config.ts), so
# Next.js nests the traced standalone output under apps/web/ instead of
# putting server.js at the output root -- copy the whole nested tree and
# point CMD/static/public copies at that same nested path.
COPY --from=build --chown=appuser:appuser /app/.next/standalone ./
COPY --from=build --chown=appuser:appuser /app/.next/static ./apps/web/.next/static
COPY --from=build --chown=appuser:appuser /app/public ./apps/web/public

EXPOSE 3000
ENV PORT=3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "require('http').get('http://localhost:3000/', r => process.exit(r.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node", "apps/web/server.js"]
