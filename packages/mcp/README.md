# vinci-mcp

Authored MCP tools served by the local daemon at `POST /mcp`.

| Tool | Daemon |
| --- | --- |
| `vinci.models_list` | `GET /models` |
| `vinci.skills_search` | `GET /skills` |
| `vinci.image_generate` | `POST /runs` (`@tryvinci/image-generate`) |
| `vinci.video_generate` | `POST /runs` (`@tryvinci/video-generate`) |
| `vinci.media_inspect` | asset metadata |
| `vinci.workflow_run` | `POST /runs` |
| `vinci.jobs_get` | `GET /jobs/{id}` |
| `vinci.jobs_cancel` | `POST /runs/{id}/cancel` |
| `vinci.cost_estimate` | estimate only |
| `vinci.presets_list` | `GET /presets` (generic, partner, and custom, each tagged with `source`) |
| `vinci.adapts_run` | `POST /adapts/batch` with one item (`asset_id` or `source_url`, plus `preset_ids`). Returns `batch_id`. |
| `vinci.batch_status` | `GET /adapts/batch/{batch_id}` |
| `vinci.olf_validate` | `vinci olf validate` (only when `vinci-olf` is installed, as the `/olf` routes) |
| `vinci.olf_resolve` | `GET /olf/shot` without the prices: resolved view, hashes, prompts, references |
| `vinci.olf_status` | `vinci olf status`: takes with kind, status and `stale` |
| `vinci.olf_render` | `POST /olf/render`: plans first; a paid render runs only within `max_cost`, and a model with no flat price is refused (`olf_tools.py`) |

`vinci mcp print-config` prints a client config whose URL is the daemon `/mcp` endpoint.

Remote MCP servers that publish OAuth discovery and dynamic client registration can sign in through `POST /providers/{id}/oauth` and `GET /providers/oauth/callback`. The sign-in asks for the protected resource's `scopes_supported`, plus `offline_access` when the authorization server lists it (COREPRODUC-610: before, only `openid offline_access`, which Magnific's audience and Higgsfield's email claim need more than). The callback answers with `result_page()` (`vinci_mcp/oauth.py`): one page in the Studio's dark tokens, with no script and no files, which the hosted backend sends too. Other servers connect and list tools; generation still requires an explicit tool mapping or Vinci's own `vinci.*` tools.

Higgsfield (`mcp_higgsfield`) and Magnific (`mcp_magnific`) are presets with a live tool mapping (`connectors.py`, captured from a signed-in `tools/list` on 2026-11-12, COREPRODUC-614):

| | Higgsfield | Magnific |
| --- | --- | --- |
| Rows | Seedream 4.5, Soul 2.0 (stills, 1 credit), Hailuo 2.3 Fast 6 s 768p (clip, 4 credits) | Seedream 4.5, Mystic 2.5 (stills, 50 credits), Hailuo 2.3 Fast 6 s 768p (clip, 150 credits) |
| Generate | `generate_image`, `generate_video` with `{"params": {model, prompt, aspect_ratio, use_unlim: false, medias}}` | `images_generate` (`mode`), `video_generate` (`slug`, `keyframes.start`) |
| Status | `job_status {jobId}`: `generation.status`, `results.rawUrl` | `creation_status {creationIdentifier}`: `status`, `results.url` |
| Price preview (free) | the generate tool with `get_cost: true` | `simulate_cost {tool, arguments}` |
| Start frame | `media_upload` + PUT + `media_confirm`; a public link: `media_import_url` | `creations_request_upload` + PUT + `creations_finalize_upload` (not in the library); a link: `creations_upload_image` |

A row's price is in the provider's own credits (currency `Higgsfield credits` / `Magnific credits`). Before each run the adapter asks the free preview, and a live price above the row's price stops the run before any spend. The PUT sends a named User-Agent: Higgsfield's upload host refuses Python's default one (Cloudflare 1010). A host with several processes keeps a pending sign-in with `pending_export` / `pending_import`. The package's `__init__` loads the authored server on first use, so a host that only runs connectors (the hosted Studio) installs `vinci-mcp` with no deps. The Mac app bundle lock does not yet include the `mcp` package; regenerate it on a macOS builder before shipping a desktop build that signs in.
