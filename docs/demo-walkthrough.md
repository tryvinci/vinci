# Demo walkthrough: Vinci for Higgsfield and Magnific users

A 20-minute live demo script for people who make images and video in Higgsfield or Magnific today. It shows the same jobs in Vinci Studio, then the things a single-vendor app cannot do: one canvas for every provider, the price before each run, and a receipt after it.

Rehearse in free demo mode (mock outputs, $0). Run the demo itself live.

## Before the call (10 min)

1. Start live: put provider keys in `.env` (or use **Connect**), then run `VINCI_ALLOW_LIVE_SPEND=1 ./scripts/vinci studio` and open `http://127.0.0.1:4311`. Without `VINCI_ALLOW_LIVE_SPEND=1` the Studio stays in demo mode.
2. In **Connect**, use **Sign in** for Higgsfield and Magnific (OAuth, tokens stay on this machine), or add a Wavespeed key. One Wavespeed key covers every step below.
3. Have ready: one product photo and one face or character still (consented, not scraped).
4. Pre-render one take per segment. Live video takes 2-5 minutes, so show the saved take from the feed while the new one runs.

## What maps to what

| They use today | In Vinci | Where |
| --- | --- | --- |
| Higgsfield / Magnific image generation | Prompt bar, any image model | **Image** |
| Image with a reference (edit, restyle) | **Add reference** (`+`), or hover a result, then **Use as reference** | **Image** |
| Text to video | **Create** tab | **Video** |
| Image to video | Hover a still, then **Animate** (sets the start frame) | **Image** → **Video** |
| Higgsfield Keyframes / Veo first-last frame | **Start frame** and **End frame** in the Create tab, or the **First Last Frame** template | **Video**, **Explore** |
| Higgsfield Soul ID (consistent character) | **Soul Character** template | **Explore** |
| Higgsfield Popcorn (shot sets) | **Popcorn Sequence** template | **Explore** |
| Magnific upscaler | **Upscale Still** | **Image** menu |
| Higgsfield Genjutsu (video-to-video motion transfer) | Not yet. See [the gap](#genjutsu-honest-answer) | - |

## Segment 1: image, with and without a reference (5 min)

1. Open **Image**. Click the model chip and type `Higgsfield`, then `Magnific`, in the search. Their models are in the same list. Pick **Nano Banana Pro**.
2. Prompt: `matte black sneaker on wet asphalt at night, neon reflections, low angle, product hero shot`. Set the aspect chip to 9:16.
3. Point at the price on **Generate**. Say: "You see the cost before you spend it." Generate.
4. Switch the model chip to **Seedream 4.5** and generate again. Say: "Same prompt, another model, no new subscription. Keep the best take."
5. With a reference: hover the first result, press **Use as reference** (the still shows in the prompt bar), and prompt `same sneaker on a white marble plinth, soft studio light, clean beige backdrop`. Generate.

## Segment 2: video, text and image to video (5 min)

1. Open **Video** (**Create** tab). Prompt: `slow push-in on a matte black sneaker on wet asphalt at night, rain falling, neon reflections`. 5s, 16:9, Kling 2.6 Pro. Generate (text to video).
2. Go back to **Image**, hover the plinth still, press **Animate**. It opens **Video** with that still as the **Start frame**. Prompt `the camera slowly orbits the sneaker on the marble plinth`, 9:16, Generate.
3. Mention **Start frame** + **End frame** (Higgsfield Keyframes equivalent) and **Extend Video**.
4. Open **Cost report**. Show the per-run receipts and the total. Say: "This is a number you can put on a client invoice."

## Segment 3: Canvas (5 min)

This is the part a single-vendor app does not have.

1. **Explore** › **Product reveal**. It opens on **Canvas**: **Image Gen** feeds **Animate image**.
2. Click **Image Gen**. Each node has its own prompt, model chip, aspect, and count. Type the product prompt here.
3. Click **Animate image** and give it a motion prompt. The selection bar shows "up to $…" for this node and the nodes that feed it.
4. Press **Run** (top right). Finished nodes show **Saved** when a re-run reuses them, so only changed nodes cost money.
5. Open **Timeline** to show the results in order.

## Segment 4: one Higgsfield special (3 min)

Pick one, based on the audience:

- **Soul Character** (creators, influencer brands): **Explore** › Soul Character. **Image Gen** makes a character sheet; **Image Editor** keeps the identity in a new scene. Set both model chips (for example Seedream 4.5), write both prompts, press **Run**. Add their own still as a reference for their own character.
- **Still to talk / Talking photo** (ads, UGC): animate a still into a talking take. Same job as Higgsfield's talking avatars.

## Genjutsu: honest answer

[Higgsfield Genjutsu](https://higgsfield.ai/genjutsu) edits existing footage: motion transfer and object or character swap on a 3-30 s source clip. Vinci has no Genjutsu equivalent yet. The Video page's **Motion control** tab is camera motion (pan, orbit, push-in), not motion transfer. The closest today is lipsync on an existing video and "keyframe still, then image to video" on the canvas.

What to say: "If you depend on Genjutsu, keep it for that one job. Vinci connects to your Higgsfield account, so other Higgsfield models run inside the same canvas, next to Google, Wavespeed, and fal." Do not promise a date.

## Close (2 min)

- Free studio, no subscription. You pay providers per generation at their own API rates.
- Keys and files stay on your machine.
- Demo mode costs $0, so the team can learn it without a budget.
- Next step: run the [quickstart](quickstart.md), then [make your first scene](first-film.md).

## Common questions

- **"Is it cheaper than Higgsfield?"** Sometimes. Vinci adds nothing on top of the provider price and shows it before each run. Magnific sometimes undercuts direct API prices. Do not say "always cheaper".
- **"Can I use my Higgsfield credits?"** Yes. **Sign in** with Higgsfield runs against your own account.
- **"Do outputs look worse in demo mode?"** Demo outputs are mock placeholders. Show live takes for quality.
