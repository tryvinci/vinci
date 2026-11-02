# Vinci Studio (Android)

WebView shell around the TypeScript Studio (`:4311`). The daemon HTML `/studio` still loads, but it is deprecated.

Provider keys are **not** stored on the phone. Paste them in Studio; the daemon writes `~/.vinci/keys` (mode 0600) or the OS keychain on the machine running `vinci-daemon`.

## Point the phone at a daemon

On the machine with the runtime:

```bash
cd vinci
source .venv/bin/activate
./scripts/vinci init --demo
./scripts/vinci studio --lan --no-open
```

Use the printed `Vinci Studio (LAN TS) → http://…:4311` URL in the app's URL bar. The CLI prints it only when the TypeScript Studio is running; without Node it prints just the deprecated `/studio` LAN URL.

Android emulator → host: `http://10.0.2.2:4311` (the app default). Without Node on the host, use the deprecated HTML fallback at `http://10.0.2.2:4310/studio`.

## Build

Open `apps/android` in Android Studio and run the `app` configuration. This tree does not vendor a Gradle wrapper JAR.
