# Build stage
FROM node:22-alpine AS builder

# Install openssl for Prisma and other native modules that need it
RUN apk add --no-cache openssl

WORKDIR /app

# Copy all files first to check project type
COPY . .

# Detect if this is a Node.js project or simple static HTML
RUN if [ -f package.json ]; then \
      echo "Node.js project detected (package.json found)"; \
      echo "nodejs" > .project-type; \
    else \
      echo "Simple static HTML project detected (no package.json)"; \
      echo "static-html" > .project-type; \
    fi

# Install dependencies only if package.json exists
RUN if [ -f package.json ]; then \
      if [ -f package-lock.json ]; then \
        npm ci --ignore-scripts 2>/dev/null || { \
          echo "⚠️  package-lock.json out of sync, regenerating with npm install..."; \
          rm -f package-lock.json; \
          npm install --ignore-scripts; \
        }; \
      else \
        npm install --ignore-scripts; \
      fi; \
      npm rebuild 2>/dev/null || true; \
      if grep -q '"postinstall"' package.json; then \
        npm run postinstall; \
      fi; \
    fi

# Remove stale build artifacts that may have been copied from source
RUN rm -rf .next dist build

# Build-time placeholder env vars for common auth/db libraries.
# During next build, route modules are imported for page data collection.
# Auth libraries (better-auth, Auth.js, NextAuth) crash if their URL/secret
# env vars are undefined. These placeholders prevent that.
# They are harmless for non-Next.js apps and are cleared in the production stage.
ENV BUILD_MODE=1
ENV BETTER_AUTH_URL=http://localhost:3000
ENV BETTER_AUTH_SECRET=build-placeholder
ENV AUTH_SECRET=build-placeholder
ENV AUTH_URL=http://localhost:3000
ENV AUTH_TRUST_HOST=true
ENV NEXTAUTH_SECRET=build-placeholder
ENV NEXTAUTH_URL=http://localhost:3000
ENV MONGODB_URI=mongodb://placeholder:27017/placeholder
ENV DATABASE_URL=postgresql://placeholder:placeholder@localhost:5432/placeholder
ENV SESSION_SECRET=build_time_placeholder_min_32_chars_long

# Detect app type and conditionally build
RUN if [ "$(cat .project-type)" = "static-html" ]; then \
      echo "Simple static HTML - no build needed"; \
      echo "static-html" > .app-type; \
    elif grep -q '"build":' package.json; then \
      echo "Build script found, running build..."; \
      npm run build; \
      if [ -d .next/standalone ]; then \
        echo "nextjs-standalone" > .app-type; \
      elif [ -d .next ] && [ -f .next/BUILD_ID ]; then \
        echo "nextjs" > .app-type; \
      elif [ -d dist ]; then \
        if [ -d dist/public ] && ([ -f dist/index.cjs ] || [ -f dist/index.js ]); then \
          echo "Detected Replit project (dist/public + dist/index.cjs)"; \
          echo "Serving frontend only from dist/public/"; \
          echo "replit-frontend" > .app-type; \
        elif [ -f dist/index.cjs ] || [ -f dist/index.js ]; then \
          echo "Detected Node.js backend (dist/index.cjs without dist/public)"; \
          echo "nodejs-backend" > .app-type; \
        else \
          echo "static-dist" > .app-type; \
        fi; \
      elif [ -d build ]; then \
        echo "static-build" > .app-type; \
      elif DIST_DIR=$(find . -maxdepth 1 -type d -name 'dist-*' | head -1) && [ -n "$DIST_DIR" ]; then \
        DIST_DIR=$(basename "$DIST_DIR"); \
        echo "Detected custom dist folder: $DIST_DIR"; \
        mv "$DIST_DIR" dist; \
        echo "static-dist" > .app-type; \
      else \
        echo "ERROR: No build output found in .next, dist, build, or dist-*" && exit 1; \
      fi; \
    else \
      echo "No build script found, assuming Node.js/Express backend"; \
      echo "nodejs-backend" > .app-type; \
    fi

# Prune dev dependencies (except for Next.js standard mode which may need them at runtime)
RUN APP_TYPE=$(cat .app-type) && \
    if [ "$APP_TYPE" != "nextjs" ] && [ "$APP_TYPE" != "nextjs-standalone" ] && [ "$APP_TYPE" != "static-html" ]; then \
      npm prune --omit=dev 2>/dev/null || true; \
    fi

# Production stage
FROM node:22-alpine

RUN apk add --no-cache openssl

WORKDIR /app

# Copy built app and production dependencies from builder
COPY --from=builder /app ./

# For Next.js standalone: set up the standalone server without overwriting .next/ manifests
# Standalone output lives in .next/standalone/ but does NOT include:
#   - .next/routes-manifest.json, build-manifest.json, and other manifests
#   - .next/static/ (static assets)
#   - public/ (public assets)
# So we selectively copy standalone's server.js and node_modules, then merge
# its .next/server/ into the existing .next/ which already has manifests and static.
RUN if [ -f .app-type ] && [ "$(cat .app-type)" = "nextjs-standalone" ]; then \
      cp .next/standalone/server.js . && \
      if [ -d .next/standalone/node_modules ]; then \
        rm -rf node_modules && \
        cp -a .next/standalone/node_modules ./node_modules; \
      fi && \
      if [ -d .next/standalone/.next/server ]; then \
        cp -a .next/standalone/.next/server .next/server; \
      fi && \
      rm -rf .next/standalone; \
    fi

# Install serve globally for static apps (Vite/CRA/Replit-frontend/simple HTML) only
RUN APP_TYPE=$(cat .app-type) && \
    if [ "$APP_TYPE" = "static-html" ] || [ "$APP_TYPE" = "static-dist" ] || [ "$APP_TYPE" = "static-build" ] || [ "$APP_TYPE" = "replit-frontend" ]; then \
      npm install -g serve; \
    fi

# Create entrypoint script based on detected app type
RUN APP_TYPE=$(cat .app-type) && \
    printf '#!/bin/sh\n' > /entrypoint.sh && \
    if [ "$APP_TYPE" = "static-html" ]; then \
      printf 'exec serve . -s -l 3000\n' >> /entrypoint.sh; \
    elif [ "$APP_TYPE" = "nextjs-standalone" ]; then \
      printf 'exec node server.js\n' >> /entrypoint.sh; \
    elif [ "$APP_TYPE" = "nextjs" ]; then \
      printf 'exec node_modules/.bin/next start -p 3000\n' >> /entrypoint.sh; \
    elif [ "$APP_TYPE" = "replit-fullstack" ]; then \
      printf 'exec npm start\n' >> /entrypoint.sh; \
    elif [ "$APP_TYPE" = "replit-frontend" ]; then \
      printf 'exec serve dist/public -s -l 3000\n' >> /entrypoint.sh; \
    elif [ "$APP_TYPE" = "static-dist" ]; then \
      printf 'exec serve dist -s -l 3000\n' >> /entrypoint.sh; \
    elif [ "$APP_TYPE" = "static-build" ]; then \
      printf 'exec serve build -s -l 3000\n' >> /entrypoint.sh; \
    elif [ "$APP_TYPE" = "nodejs-backend" ]; then \
      printf 'exec npm start\n' >> /entrypoint.sh; \
    fi && \
    chmod +x /entrypoint.sh

# Clear build-time placeholders so they don't leak into runtime.
# Actual values are injected by the platform (Northflank secrets) at container start.
ENV BUILD_MODE=
ENV BETTER_AUTH_URL=
ENV BETTER_AUTH_SECRET=
ENV AUTH_SECRET=
ENV AUTH_URL=
ENV AUTH_TRUST_HOST=
ENV NEXTAUTH_SECRET=
ENV NEXTAUTH_URL=
ENV MONGODB_URI=
ENV DATABASE_URL=
ENV SESSION_SECRET=

ENV PORT=3000
ENV HOSTNAME=0.0.0.0

EXPOSE 3000

CMD ["/entrypoint.sh"]
