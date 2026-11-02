# Vinci Studio (Mac)

WKWebView shell loads the **TypeScript Next.js Studio** from the bundled standalone server (full UI). The daemon HTML `/studio` is a deprecated CLI/browser fallback only.

The Mac app does not store provider keys. Paste keys in Studio; they stay in `~/.vinci/keys` (0600) or the OS keychain on the daemon host.

Alpha packaging: [docs/MAC_ALPHA.md](../../docs/MAC_ALPHA.md).

## Run without Xcode

```bash
cd vinci
source .venv/bin/activate
./scripts/vinci init --demo
./scripts/vinci studio
```

That opens the TypeScript Studio (`:4311`) in the default browser, or the deprecated `/studio` page if Node is missing. Add to Dock from the browser if you want a PWA.

## Build the native wrapper (macOS)

```bash
cd apps/mac
swiftc -parse-as-library -O -target arm64-apple-macos13.0 \
  -framework Cocoa -framework WebKit -framework AVFoundation \
  VinciStudio.swift SmokeRunner.swift -o VinciStudio
./VinciStudio
```

The wrapper starts its bundled daemon and TypeScript Studio on a free local port and loads it. For a runtime on another machine, run `./scripts/vinci studio --lan` there and open the printed LAN URL in a browser.
