# Vinci Studio (Mac)

WKWebView shell around the same Studio the daemon serves at `/studio`.

The Mac app does not store provider keys. Paste keys in Studio; they stay in `~/.vinci/keys` (0600) or the OS keychain on the daemon host.

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
swiftc -O -framework Cocoa -framework WebKit VinciStudio.swift -o VinciStudio
VINCI_STUDIO_URL=http://127.0.0.1:4310/studio ./VinciStudio
```

Point `VINCI_STUDIO_URL` at a daemon on the LAN (`./scripts/vinci studio --lan`) if the runtime is on another machine.
