import {
  authConfigured,
  authorized,
  bridgeJournalAuthorized,
  csrfCookie,
  instanceSecret,
  loginPage,
  mintCsrfToken,
  mintSession,
  readCookie,
  sameOriginOk,
  sessionCookie,
  type Env,
} from "./auth";
import { VinciHost } from "./host";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/healthz") {
      return Response.json({
        status: "ok",
        surface: "worker",
        auth: authConfigured(env),
      });
    }

    if (url.pathname.startsWith("/__vinci/journal/")) {
      if (!authConfigured(env)) {
        return Response.json({ error: "misconfigured" }, { status: 503 });
      }
      if (!bridgeJournalAuthorized(request, env)) {
        return Response.json({ error: "unauthorized" }, { status: 401 });
      }
      const id = env.HOST.idFromName("default");
      return env.HOST.get(id).fetch(request);
    }

    if (!authConfigured(env)) {
      return Response.json(
        { error: "misconfigured", detail: "Set VINCI_INSTANCE_SECRET (>=16 chars) before deploy." },
        { status: 503 },
      );
    }

    if (url.pathname === "/readyz") {
      if (!(await authorized(request, env))) {
        return Response.json({ error: "unauthorized" }, { status: 401 });
      }
      const id = env.HOST.idFromName("default");
      const stub = env.HOST.get(id);
      try {
        const upstream = await stub.fetch(new Request("http://do/healthz", { method: "GET" }));
        if (upstream.ok) {
          return Response.json({ status: "ready", surface: "worker", container: true });
        }
      } catch {
        /* fall through */
      }
      return Response.json({ status: "degraded", container: false }, { status: 503 });
    }

    if (url.pathname === "/_auth/login") {
      if (request.method === "GET") {
        const csrf = mintCsrfToken();
        return new Response(loginPage(csrf), {
          headers: {
            "content-type": "text/html; charset=utf-8",
            "set-cookie": csrfCookie(csrf),
          },
        });
      }
      if (request.method === "POST") {
        if (!sameOriginOk(request)) {
          return new Response("forbidden", { status: 403 });
        }
        const form = await request.formData();
        const csrf = String(form.get("csrf") || "");
        const cookieCsrf = readCookie(request, "vinci_csrf") || "";
        if (!csrf || csrf !== cookieCsrf) {
          return new Response(loginPage(mintCsrfToken(), "CSRF check failed."), {
            status: 403,
            headers: { "content-type": "text/html" },
          });
        }
        const secret = String(form.get("secret") || "");
        if (secret !== instanceSecret(env)) {
          return new Response(loginPage(csrf, "Invalid secret."), {
            status: 401,
            headers: { "content-type": "text/html" },
          });
        }
        const token = await mintSession(env);
        return new Response(null, {
          status: 302,
          headers: {
            location: "/studio",
            "set-cookie": sessionCookie(token, 60 * 60 * 24 * 14),
          },
        });
      }
      return new Response("method not allowed", { status: 405 });
    }

    if (!(await authorized(request, env))) {
      if (request.method === "GET" && !url.pathname.startsWith("/_")) {
        return new Response(null, { status: 302, headers: { location: "/_auth/login" } });
      }
      return Response.json({ error: "unauthorized" }, { status: 401 });
    }

    if (["POST", "PUT", "PATCH", "DELETE"].includes(request.method) && !request.headers.get("authorization")) {
      if (!sameOriginOk(request)) {
        return Response.json({ error: "forbidden" }, { status: 403 });
      }
    }

    const id = env.HOST.idFromName("default");
    const stub = env.HOST.get(id);
    return stub.fetch(request);
  },
};

export { VinciHost };
