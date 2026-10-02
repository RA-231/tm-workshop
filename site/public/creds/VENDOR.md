# The scanner's QR decoder

`creds/jsQR.js` is **not in this repo**. It is [jsQR](https://github.com/cozmo/jsQR)
**1.4.0**, Apache-2.0, pinned as a dependency in `site/package.json` and copied
out of `node_modules` into the published site by `site/Dockerfile` at build time.
`creds/jsQR.LICENSE` comes along with it, because Apache-2.0 requires the licence
to travel with redistributed code and the built image redistributes it.

Both files appear when you run `task up:docs`, and both are gitignored.

## Why a dependency rather than a committed copy

It used to be committed — a 250KB minified blob, pinned by a hash written into
this file by hand. The dependency is better on every axis that matters:

- **npm verifies it.** `package-lock.json` carries
  `sha512-dxLob7q65Xg2DvstYkRpkYtmKm2sPJ9oFhrhmudT1dZvNFFTlroai3AWSpLey/w5vMcLBXRgOJsbXpdN9HzU/A==`
  and checks it on every install. A vendored file is only as trustworthy as the
  person who last looked at it.
- **The build was never offline anyway.** `site/Dockerfile` runs `npm install`
  for Astro, so vendoring one file while fetching hundreds bought nothing.
- **Nothing to review in a diff.** Minified bundles are unreadable in review;
  a version bump in a lockfile is not.

The property that *is* worth keeping is that the **page** makes no network
requests once built: the decoder is served from the same origin as the page, not
from a CDN at run time. A conference network should never sit between an
attendee and the code that reads their credential. That still holds — the fetch
happens at build, on your machine, not in their browser.

## Verifying it, if you want to

```bash
docker compose exec docs sha256sum /usr/share/nginx/html/creds/jsQR.js
# expect bc40c8a15196236b2314db0856f72ca0b49980cd5413b8c852a7349f5fee0859

curl -sO https://registry.npmjs.org/jsqr/-/jsqr-1.4.0.tgz
tar xzOf jsqr-1.4.0.tgz package/dist/jsQR.js | sha256sum   # must match
```
