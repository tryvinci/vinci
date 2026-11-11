# vinci-olf

The Vinci movie engine (**build the world once, render every episode**): a reader, validator and renderer for the **Open Lore Format (OLF) v0.1**.
A game engine runs a scene file; this engine runs a show: a bible (style, characters, locations,
props, voices), seasons (optional), episodes, scenes and shots, and the takes rendered from them.

- Spec: [`SPEC.md`](SPEC.md) (canonical copy, CC-BY-4.0).
- Schema: [`vinci_olf/schema.json`](vinci_olf/schema.json), one `$defs` entry per object.
- Conformance sample: [`conformance/tidewatch/`](conformance/tidewatch/) and its expected resolved output.
- How the engine works: [`docs/OLF_ENGINE.md`](../../docs/OLF_ENGINE.md).

```bash
./scripts/vinci olf validate -C packages/olf/conformance/tidewatch
./scripts/vinci olf resolve e02/s03/sh014 -C packages/olf/conformance/tidewatch
./scripts/vinci olf render e02/s03/sh014 -C <your copy of the project>   # demo mode: $0
./scripts/vinci olf status -C <your copy of the project>
./scripts/vinci olf review e02/s03/sh014/v1 --status approved -C <project>
./scripts/vinci olf select e02/s03/sh014 --keyframe kf1 -C <project>
./scripts/vinci olf template anime/tu-to-eyes --shot e02/s03/sh014 -C <project>   # a camera move, $0
./scripts/vinci olf previs e02 -C <project>   # the e-conte sheet (PDF) and the animatic, $0
```

In the Vinci Studio, the **Shows** page is the editor over the same engine (daemon routes `/olf/*`).

The reader needs only `ruamel.yaml` (YAML 1.2) and `jsonschema`. Rendering needs the Vinci
runtime (`pip install -e "packages/olf[render]"`).

License: Apache-2.0 (code and schema). The spec text is CC-BY-4.0. The camerawork template library (`vinci_olf/camerawork/`) is CC0-1.0.
