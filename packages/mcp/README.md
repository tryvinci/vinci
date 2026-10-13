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

`vinci mcp print-config` prints a client config whose URL is the daemon `/mcp` endpoint.

Remote MCP servers that publish OAuth discovery and dynamic client registration can sign in through `POST /providers/{id}/oauth` and `GET /providers/oauth/callback`. Higgsfield (`mcp_higgsfield`) and Magnific (`mcp_magnific`) are presets. Other servers connect and list tools; generation still requires an explicit tool mapping or Vinci's own `vinci.*` tools. The Mac app bundle lock does not yet include the `mcp` package; regenerate it on a macOS builder before shipping a desktop build that signs in.
