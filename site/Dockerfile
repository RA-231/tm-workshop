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
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
# Keeps the published port in directory redirects -- see the comment in the file.
COPY site/nginx/default.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
