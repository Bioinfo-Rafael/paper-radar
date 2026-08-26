const encoder = new TextEncoder();

function hexToBytes(hex) {
  const pairs = hex.match(/.{1,2}/g) || [];
  return new Uint8Array(pairs.map((byte) => Number.parseInt(byte, 16)));
}

async function verifyDiscordRequest(request, body, publicKey) {
  const signature = request.headers.get("X-Signature-Ed25519");
  const timestamp = request.headers.get("X-Signature-Timestamp");
  if (!signature || !timestamp) return false;
  const key = await crypto.subtle.importKey(
    "raw",
    hexToBytes(publicKey),
    { name: "Ed25519" },
    false,
    ["verify"],
  );
  return crypto.subtle.verify(
    "Ed25519",
    key,
    hexToBytes(signature),
    encoder.encode(timestamp + body),
  );
}

async function dispatchWorkflow(env, category) {
  const endpoint = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/more.yml/dispatches`;
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "Content-Type": "application/json",
      "User-Agent": "paper-radar-discord-more",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref: env.GITHUB_REF || "main", inputs: { category, count: "5" } }),
  });
  if (!response.ok) throw new Error(`GitHub dispatch failed: ${response.status}`);
}

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") return new Response("Not found", { status: 404 });
    const body = await request.text();
    if (!(await verifyDiscordRequest(request, body, env.DISCORD_PUBLIC_KEY))) {
      return new Response("Invalid signature", { status: 401 });
    }
    const interaction = JSON.parse(body);
    if (interaction.type === 1) return Response.json({ type: 1 });
    const category = interaction.data?.options?.find((item) => item.name === "category")?.value;
    if (interaction.type !== 2 || interaction.data?.name !== "more" || !["bioinfo", "ml", "frontier"].includes(category)) {
      return Response.json({ type: 4, data: { content: "Unsupported command.", flags: 64 } });
    }
    ctx.waitUntil(dispatchWorkflow(env, category));
    return Response.json({
      type: 4,
      data: { content: `Searching for 5 more ${category} papers…`, flags: 64 },
    });
  },
};
