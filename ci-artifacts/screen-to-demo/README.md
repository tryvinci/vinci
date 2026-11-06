# screen-to-demo sample artifacts

Real non-private screen footage sample for PR #9. Input: 7.56s rough recording
assembled from two public screenshots (github.com/tryvinci/vinci repo page and
README view) with a fade. Output: `sample-demo.mp4` - full 7.56s, h264+aac,
zoom-in and spotlight effects rendered, captions burned.

- `frame-zoom.png` - t=1.5s: zoom-in effect + burned caption on the repo page.
- `frame-spotlight.png` - t=6.0s: yellow spotlight box + burned caption on the README view.

Honest limits of this $0 mock path: speech is stubbed (transcription is the
engine's mock, voiceover is tone blips, no real voices), and effect boxes land
at deterministic plan coordinates, not content-aware regions.
