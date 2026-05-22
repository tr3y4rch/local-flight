export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/local-flight/privacy" || url.pathname === "/local-flight/privacy/") {
      return Response.redirect(new URL("/privacy", url), 301);
    }

    if (request.method === "HEAD") {
      const getRequest = new Request(request, { method: "GET" });
      const response = await env.ASSETS.fetch(getRequest);
      return new Response(null, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    }

    return env.ASSETS.fetch(request);
  },
};
