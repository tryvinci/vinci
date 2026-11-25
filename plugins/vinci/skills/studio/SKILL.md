---
name: studio
description: Make images and videos in the user's Vinci Studio with the vinci MCP tools (vinci.*). Use when the user asks to generate, animate or price an image or video clip with Vinci, or to check a Vinci run. Covers price first, polling, start images, refused calls and how to write video prompts that move.
---

# Vinci Studio

The `vinci` MCP server runs the user's Vinci Studio. A run costs the same credits as in the Studio and shows in the Studio (`studio_url` in each run). The hosted server is `https://app.tryvinci.com/mcp`. The first call opens a Vinci sign-in page. There is no API key.

## Tools

Read the tool list from the server (`tools/list`). It is the source of truth: new tools come with their own descriptions. These are the core tools; the local daemon has more (skills, workflows, Shows).

| Tool | Use | Credits |
| --- | --- | --- |
| `vinci.models_list` | Models the user can run (`capability`: `image` or `video`), with `pricing`, `constraints` and `capabilities` (`t2i`, `i2i`, `t2v`, `i2v`) | 0 |
| `vinci.cost_estimate` | Price of one run (`model_id`, `inputs`) and the user's `balance` and `enough` | 0 |
| `vinci.image_generate` | Start an image run (`prompt`; optional `model_id`, `inputs`, `max_credits`) | model price |
| `vinci.video_generate` | Start a video run (same arguments) | clip price |
| `vinci.jobs_get` | Read a run (`run_id`). Reading it also moves it forward | 0 |
| `vinci.media_inspect` | Read one asset (`vinci://assets/{id}` or the id): type, size, url | 0 |

## Steps

1. **Pick a model.** Call `vinci.models_list` with the capability. Use a `model_id` from it, never a guessed id. Read `constraints` for the allowed `inputs` (for example `aspect_ratio`, `resolution`, `duration` in seconds). No `model_id` gives the default model.
2. **Price first.** Call `vinci.cost_estimate` with the same `model_id` and `inputs`. Tell the user the credits and the balance. Get the user's yes before each paid run. A run on the user's own provider account (Connect) costs 0 credits.
3. **Start with a cap.** Send `max_credits` equal to the price the user agreed to. A higher price refuses the run, and nothing starts.
4. **Poll.** The start returns a `run_id`. Call `vinci.jobs_get` every 10–20 s until `state` is `completed` or `failed`. On the hosted server nothing runs between reads, so do not stop polling early. Do not start the run again to "retry": each start is a new charge.
5. **Report.** When completed, each item in `outputs` has an `id` and a `url`. Give the user the url and the `studio_url`.

## Start images

A start image is an **asset id from an earlier output** (`outputs[].id`), not a web link. Put it in `inputs.image` (or `inputs.first_frame_url`). A start image switches the run to image-to-image or image-to-video, so pick a model whose `capabilities` has `i2i` or `i2v`. Common chain: make a still, check it with the user, then animate it with `vinci.video_generate`.

## Refused calls

A refused call is a tool result with `isError: true` and one sentence that says what to fix: not enough credits, a price above `max_credits`, a model that cannot make this kind of output, a bad argument. Read the sentence, fix that one thing, and tell the user. Do not loop on the same call.

## Video prompts that move

These rules come from the Seedance prompt reference that the Vinci Shows engine uses ([ai-filmmaking-camera-control-seedance-2-5](https://github.com/sirioberati/ai-filmmaking-camera-control-seedance-2-5), MIT; see `docs/prompt-anatomy.md` there). They apply to most video models.

- **Write each move as start, direction and arrival.** "Mira walks from frame left toward the table, then stops beside it", not "Mira at the table". A move under about 1 m often comes out small or not at all, so make moves full steps.
- **No still words.** "Still", "motionless", "stands still", "does not move" make a statue. For a person who keeps their place, write a small live action (breathes, turns the head, shifts weight).
- **No locked-off clips.** A clip where nothing moves comes back stiff. Give the camera one move (a slow push in, a pan, a dolly) or give a person a full move.
- **Images are for looks only.** A start or reference image sets how people and things look. The model also copies its layout, so a picture of the place fixes the framing. Write the blocking and the moves in words.
- **One shot, one idea.** Name the subject, the action, the camera move and the look, in that order. Give sizes and places in the frame ("fills half the frame height, at frame left") when framing matters.

## Local daemon (option)

The open-source Vinci runtime serves the same tool names at `POST /mcp` on the local daemon (default `http://127.0.0.1:4310/mcp`), on the user's own provider keys. `./scripts/vinci mcp print-config` prints the client config. To use it in Claude Code: `claude mcp add --transport http vinci-local http://127.0.0.1:4310/mcp`. Tool list: `packages/mcp/README.md` in [tryvinci/vinci](https://github.com/tryvinci/vinci).
