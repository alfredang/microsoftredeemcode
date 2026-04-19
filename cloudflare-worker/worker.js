const ALLOWED_ORIGIN = "https://alfredang.github.io";
const REPO = "alfredang/microsoftredeemcode";

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors(origin) });
    }
    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405, headers: cors(origin) });
    }
    if (origin !== ALLOWED_ORIGIN) {
      return new Response("Forbidden", { status: 403, headers: cors(origin) });
    }

    const body = await request.text();

    const ghRes = await fetch(`https://api.github.com/repos/${REPO}/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_PAT}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "msredeem-worker",
      },
      body,
    });

    const text = await ghRes.text();
    return new Response(text || null, {
      status: ghRes.status,
      headers: { ...cors(origin), "Content-Type": "application/json" },
    });
  },
};

function cors(origin) {
  return {
    "Access-Control-Allow-Origin": origin === ALLOWED_ORIGIN ? ALLOWED_ORIGIN : "",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
  };
}
