# vinci-provider-openai

OpenAI GPT Image models via the [Images API](https://platform.openai.com/docs/api-reference/images) (`/v1/images/generations`, `/v1/images/edits`).

Set `OPENAI_API_KEY` and enable the provider (`vinci providers add openai --from-env OPENAI_API_KEY`). Live calls require `VINCI_ALLOW_LIVE_SPEND=1`.

Catalog snapshot: `packages/core/vinci_core/catalogs/openai.json` (pricing reference: medium-quality 1024×1024 from OpenAI model docs, 2026-09-28).
