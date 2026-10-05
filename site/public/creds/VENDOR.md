# The scanner's QR decoder

The scanner uses [jsQR](https://github.com/cozmo/jsQR) **1.4.0**, licensed under
Apache-2.0. It is pinned in `site/package.json` and copied
out of `node_modules` into the published site by `site/Dockerfile` at build time.
The build also copies its licence to `creds/jsQR.LICENSE` for redistribution.

Both files appear when you run `task up:docs`, and both are gitignored.

## Dependency and delivery

The decoder is installed as a dependency rather than committed as a minified
bundle:

1. **Integrity verification.** `package-lock.json` records
   `sha512-dxLob7q65Xg2DvstYkRpkYtmKm2sPJ9oFhrhmudT1dZvNFFTlroai3AWSpLey/w5vMcLBXRgOJsbXpdN9HzU/A==`
   for npm to verify during installation.
2. **Build dependencies.** `site/Dockerfile` already runs `npm install` for
   Astro and the other site dependencies.
3. **Reviewable updates.** Dependency updates appear as version and lockfile
   changes rather than minified bundle diffs.

The built site serves the decoder from the same origin as the scanner page.
The browser decodes credentials locally and does not fetch code from a CDN
or send credentials over the network. The dependency download happens during
the site build.

## Verify the decoder

```bash
# expect bc40c8a15196236b2314db0856f72ca0b49980cd5413b8c852a7349f5fee0859
docker compose exec docs sha256sum /usr/share/nginx/html/creds/jsQR.js

# must match the hash above
curl -sO https://registry.npmjs.org/jsqr/-/jsqr-1.4.0.tgz
tar xzOf jsqr-1.4.0.tgz package/dist/jsQR.js | sha256sum
```
