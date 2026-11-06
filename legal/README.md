# Legal

- `AGPL_CLEAN_ROOM.md`: the clean-room memo for the AGPL `vinci-clips` boundary. A person writes and updates it.

Git does not hold the third-party notices or the provenance of the Mac app. `scripts/mac/generate-notices-sbom.sh` writes `THIRD_PARTY_NOTICES.md` and `provenance.json` to `dist/legal/` at Mac build time. `scripts/mac/build-app.sh` copies them into the app at `Vinci Studio.app/Contents/Resources/legal/`.

The committed inputs are:

- `scripts/mac/deps.lock.json`: pinned CPython, Node.js, and FFmpeg (version, URL, sha256).
- `scripts/mac/python-bundle-runtime.lock.txt`: the hashed PyPI lock.
- `scripts/mac/python-bundle-notices.json`: the PyPI licenses and the licenses of the local trees.
- `scripts/mac/python-bundle-local.manifest.json`: the paths of the local `-e` trees.
- `package-lock.json`: the npm versions and licenses.

The build also makes these inputs (gitignored):

- `dist/notices/`: the npm graph and npm notices for the build host. `scripts/mac/prepare-studio-bundle.sh` writes them.
- `.mac-bundle-cache/python-bundle-local.digests.json`: the sha256 of each local tree. `scripts/mac/build-python-runtime.sh` writes it.
