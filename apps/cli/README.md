# @tryvinci/cli

Bin name: `vinci`. Talks to `vinci-daemon` over HTTP.

```
vinci init --demo
vinci studio
vinci studio --lan --no-open
vinci stop            # the daemon and Studio that vinci started; --force also kills a busy daemon
vinci providers add wavespeed --from-file ./key.txt
vinci olf validate -C packages/olf/conformance/tidewatch   # OLF movie engine; runs Python, no daemon
```
