// The single HTML page for the playground. No framework, no build step.

const REPO = "https://github.com/tryvinci/vinci";

const EXAMPLES = [
  "Matte black headphones on wet stone, soft studio light, product photo",
  "A lighthouse keeper reading by lamplight, 35mm film still, rain on the glass",
  "Bowl of ramen from above, steam rising, neon reflections, editorial food photo",
];

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

/** Renders the playground page. */
export function renderPage(opts: { turnstileSiteKey: string; perVisitor: number }): string {
  const turnstile = opts.turnstileSiteKey
    ? `<div class="cf-turnstile" data-sitekey="${esc(opts.turnstileSiteKey)}" data-size="flexible"></div>
       <script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>`
    : "";
  const chips = EXAMPLES.map((p) => `<button type="button" class="chip">${esc(p)}</button>`).join("");
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Try Vinci</title>
<meta name="description" content="Make an image in your browser, then run every AI model in the open-source Vinci studio.">
<meta property="og:title" content="Try Vinci in your browser">
<meta property="og:description" content="The open-source studio for making ads, films, and shorts with every AI model.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root { --bg:#f7f6f2; --ink:#16181a; --muted:#5d6266; --line:#dedbd2; --card:#ffffff; --accent:#0f766e; --accent-ink:#ffffff; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0f1112; --ink:#eceae4; --muted:#9aa0a4; --line:#2a2e30; --card:#171a1c; --accent:#2dd4bf; --accent-ink:#06201d; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 Inter, system-ui, sans-serif; }
  main { max-width: 760px; margin: 0 auto; padding: 56px 16px 72px; }
  .brand { font-weight:600; letter-spacing:.02em; color:var(--muted); font-size:14px; }
  .brand a { color:inherit; text-decoration:none; }
  h1 { font-family:"Instrument Serif", Georgia, serif; font-weight:400; font-size: clamp(40px, 7vw, 64px); line-height:1.05; margin: 18px 0 14px; }
  h1 em { color:var(--accent); }
  .lede { color:var(--muted); font-size:18px; max-width: 60ch; margin:0 0 28px; }
  form { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:16px; }
  textarea { width:100%; min-height:96px; resize:vertical; border:0; outline:none; background:transparent; color:inherit; font:inherit; font-size:17px; }
  .row { display:flex; gap:12px; align-items:center; justify-content:space-between; flex-wrap:wrap; margin-top:10px; }
  .hint { color:var(--muted); font-size:14px; }
  button.go { background:var(--accent); color:var(--accent-ink); border:0; border-radius:999px; padding:12px 22px; font:inherit; font-weight:600; cursor:pointer; }
  button.go[disabled] { opacity:.55; cursor:progress; }
  .chips { display:flex; gap:8px; flex-wrap:wrap; margin:14px 0 0; }
  .chip { border:1px solid var(--line); background:transparent; color:var(--muted); border-radius:14px; padding:6px 12px; font:inherit; font-size:13px; cursor:pointer; text-align:left; }
  .chip:hover { color:var(--ink); border-color:var(--muted); }
  .out { margin-top:24px; }
  .out img { width:100%; border-radius:16px; border:1px solid var(--line); display:block; }
  .msg { color:var(--muted); margin-top:14px; min-height:1.5em; }
  .next { margin-top:40px; border-top:1px solid var(--line); padding-top:28px; }
  .next h2 { font-family:"Instrument Serif", Georgia, serif; font-weight:400; font-size:32px; margin:0 0 10px; }
  .next h2 em { color:var(--accent); }
  pre { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; overflow-x:auto; font-size:14px; }
  .links { display:flex; gap:12px; flex-wrap:wrap; margin-top:16px; }
  .links a { color:var(--ink); border:1px solid var(--line); border-radius:999px; padding:10px 18px; text-decoration:none; font-weight:500; }
  .links a.primary { background:var(--ink); color:var(--bg); border-color:var(--ink); }
  footer { color:var(--muted); font-size:13px; margin-top:40px; }
</style>
</head>
<body>
<main>
  <div class="brand"><a href="${REPO}">Vinci · open source</a></div>
  <h1>Make something with Vinci, <em>right in your browser</em></h1>
  <p class="lede">Type a prompt and get an image from FLUX, running on Cloudflare Workers AI. You get ${opts.perVisitor} free images a day, no account needed. The full studio runs Veo 3.1, Kling 3.0, Seedance 2.0 and 90 more models on your own machine.</p>

  <form id="f">
    <label for="p" class="hint">Your prompt</label>
    <textarea id="p" maxlength="500" placeholder="Describe a shot: subject, setting, light, lens"></textarea>
    ${turnstile}
    <div class="row">
      <span class="hint" id="left">${opts.perVisitor} free images today</span>
      <button class="go" id="go" type="submit">Make it</button>
    </div>
  </form>
  <div class="chips">${chips}</div>

  <div class="msg" id="msg" role="status" aria-live="polite"></div>
  <div class="out" id="out"></div>

  <section class="next">
    <h2>Now run it on <em>every model</em></h2>
    <p class="lede">Vinci is free and MIT-licensed. Bring your own keys, try the same shot on Veo, Kling and Seedance side by side, and see the price before anything runs.</p>
<pre>git clone ${REPO} && cd vinci
python3 -m venv .venv && source .venv/bin/activate
make install && ./scripts/vinci init --demo && ./scripts/vinci studio</pre>
    <div class="links">
      <a class="primary" href="${REPO}">Star Vinci on GitHub</a>
      <a href="${REPO}#get-started-in-5-minutes">Read the quickstart</a>
    </div>
  </section>
  <footer>Images are generated by FLUX.1 Schnell on Workers AI and are not stored. Prompts are checked for safety before they run.</footer>
</main>
<script>
  const f = document.getElementById("f"), p = document.getElementById("p"), go = document.getElementById("go");
  const msg = document.getElementById("msg"), out = document.getElementById("out"), left = document.getElementById("left");
  document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => { p.value = c.textContent; p.focus(); }));
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const prompt = p.value.trim();
    if (!prompt) { msg.textContent = "Write a prompt first."; return; }
    go.disabled = true; msg.textContent = "Making your image, usually a few seconds";
    const turnstile = (document.querySelector("[name=cf-turnstile-response]") || {}).value || "";
    try {
      const res = await fetch("/api/generate", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ prompt, turnstile }) });
      const data = await res.json();
      if (!res.ok) { msg.textContent = data.error || "Something went wrong."; }
      else {
        const img = new Image(); img.alt = prompt; img.src = data.image;
        out.replaceChildren(img);
        msg.textContent = "Made with " + data.model + ". Same prompt, every model: run Vinci locally.";
      }
      if (typeof data.remaining === "number") left.textContent = data.remaining + " free images left today";
    } catch { msg.textContent = "Network error. Try again."; }
    finally { go.disabled = false; if (window.turnstile) window.turnstile.reset(); }
  });
</script>
</body>
</html>`;
}
