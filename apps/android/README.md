# Vinci Studio (Android)

WebView shell around the same Studio the daemon serves at `/studio`.

Provider keys are **not** stored on the phone. Paste them in Studio; the daemon writes `~/.vinci/keys` (mode 0600) or the OS keychain on the machine running `vinci-daemon`.

## Point the phone at a daemon

On the machine with the runtime:

```bash
cd vinci
source .venv/bin/activate
./scripts/vinci init --demo
./scripts/vinci studio --lan --no-open
```

Use the printed `Vinci Studio (LAN) → http://…:4310/studio` URL in the app's URL bar.

Android emulator → host: `http://10.0.2.2:4310/studio` (the app default).

## Build

Open `apps/android` in Android Studio and run the `app` configuration. This tree does not vendor a Gradle wrapper JAR.
