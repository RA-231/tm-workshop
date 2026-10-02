# Vendored dependency

`jsQR.js` — jsQR **1.4.0**, **Apache-2.0**, https://github.com/cozmo/jsQR
The upstream licence text is alongside it as `jsQR.LICENSE`, because Apache-2.0
requires it to travel with redistributed code and this file ships both in the
repo and inside the docs image.

## Why it is checked in rather than loaded from a CDN

This page runs at a conference, on a network nobody should trust, and it handles
a live credential. A CDN `<script>` is a third party who can change the code
between the attendee and us, and it fails entirely when the venue wifi does. A
vendored copy works with the network unplugged and can be audited at a commit.

## Provenance, verified 2026-10-01

The file is the published `dist/jsQR.js` from the npm package, unmodified:

```
npm integrity (jsqr-1.4.0.tgz)  sha512-dxLob7q65Xg2DvstYkRpkYtmKm2sPJ9oFhrhmudT1dZvNFFTlroai3AWSpLey/w5vMcLBXRgOJsbXpdN9HzU/A==
sha256 of jsQR.js               bc40c8a15196236b2314db0856f72ca0b49980cd5413b8c852a7349f5fee0859
size                            256885 bytes
```

To re-verify, or to check a future update:

```bash
curl -sO https://registry.npmjs.org/jsqr/-/jsqr-1.4.0.tgz
shasum -a 512 jsqr-1.4.0.tgz          # compare with the integrity hash above
tar xzOf jsqr-1.4.0.tgz package/dist/jsQR.js | shasum -a 256
shasum -a 256 site/public/creds/jsQR.js   # must match the line above
```
