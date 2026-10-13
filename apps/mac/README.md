# Vinci Studio (Mac)

WKWebView shell loads the **TypeScript Next.js Studio** from the bundled standalone server (full UI). The daemon HTML `/studio` remains for CLI/browser fallback only.

The Mac app does not store provider keys. Paste keys in Studio; they stay in `~/.vinci/keys` (0600) or the OS keychain on the daemon host.

Alpha packaging: [docs/MAC_ALPHA.md](../../docs/MAC_ALPHA.md).

## Run without Xcode

```bash
cd vinci
source .venv/bin/activate
./scripts/vinci init --demo
./scripts/vinci studio
```

That opens `/studio` in the default browser. Add to Dock from the browser if you want a PWA.

## Build the native wrapper (macOS)

```bash
cd apps/mac
swiftc -parse-as-library -O -target arm64-apple-macos13.0 \
  -framework Cocoa -framework WebKit -framework AVFoundation \
  VinciStudio.swift SmokeRunner.swift -o VinciStudio
VINCI_STUDIO_URL=http://127.0.0.1:4310/studio ./VinciStudio
```

Point `VINCI_STUDIO_URL` at a daemon on the LAN (`./scripts/vinci studio --lan`) if the runtime is on another machine.
