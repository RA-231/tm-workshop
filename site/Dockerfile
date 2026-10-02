# Build the Starlight docs site, serve the static output with nginx.
# Build context is the repo ROOT (see docker-compose.yml) so we can pull in
# the canonical docs/ that the site is generated from.

FROM node:22-alpine AS build
WORKDIR /app
COPY site/package.json site/package-lock.json* ./
RUN npm install
COPY site/ ./
# The canonical workshop docs; transform-docs.mjs reads these at build time.
COPY docs/ ./docs-src/
ENV DOCS_SRC=/app/docs-src

# The credential scanner's QR decoder, taken from the pinned jsqr dependency
# installed above rather than committed to the repo as a 250KB minified blob.
# npm verified its integrity hash against package-lock.json during install, so
# this is a stronger guarantee than a vendored copy with a hand-written hash.
# Apache-2.0 requires the licence to travel with redistributed code, and the
# built image redistributes it, so the LICENSE comes along.
RUN cp node_modules/jsqr/dist/jsQR.js public/creds/jsQR.js \
 && cp node_modules/jsqr/LICENSE      public/creds/jsQR.LICENSE

RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
# Keeps the published port in directory redirects -- see the comment in the file.
COPY site/nginx/default.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
