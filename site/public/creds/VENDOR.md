# Vendored dependency

`jsQR.js` — jsQR 1.4.0, MIT licensed, https://github.com/cozmo/jsQR

Checked in rather than loaded from a CDN on purpose: this page runs at a
conference, on a network nobody should trust, and it handles a live credential.
A vendored copy means the scanner works with the venue wifi switched off and
cannot be swapped out in transit.
