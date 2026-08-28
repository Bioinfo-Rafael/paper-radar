const encoder = new TextEncoder();
const CATEGORIES = new Set(["bioinfo", "ml", "frontier"]);
const COMMANDS = {
  daily: { workflow: "daily.yml", acknowledgement: (category) => `Started ${category} Daily Paper Radar.` },
  more: { workflow: "more.yml", acknowledgement: (category) => `Searching for 5 more ${category} papers…` },
};

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

function categoryForChannel(env, channelId) {
  let mapping;
  try {
    mapping = JSON.parse(env.CHANNEL_CATEGORY_MAP || "{}");
  } catch {
    throw new Error("CHANNEL_CATEGORY_MAP must be valid JSON");
  }
  const category = mapping[String(channelId || "")];
  return CATEGORIES.has(category) ? category : null;
}

async function dispatchWorkflow(env, commandName, category) {
  const command = COMMANDS[commandName];
  const endpoint = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/${command.workflow}/dispatches`;
  const inputs = commandName === "more" ? { category, count: "5" } : { category };
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "Content-Type": "application/json",
      "User-Agent": "paper-radar-discord-commands",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref: env.GITHUB_REF || "main", inputs }),
  });
  if (!response.ok) {
    throw new Error(
      `GitHub workflow dispatch failed: workflow=${command.workflow} category=${category} status=${response.status}`,
    );
  }
}

async function updateInteraction(interaction, content) {
  const endpoint = `https://discord.com/api/v10/webhooks/${interaction.application_id}/${interaction.token}/messages/@original`;
  const response = await fetch(endpoint, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!response.ok) {
    throw new Error(`Discord interaction update failed: status=${response.status}`);
  }
}

async function runCommand(env, interaction, commandName, category) {
  let content;
  try {
    await dispatchWorkflow(env, commandName, category);
    content = COMMANDS[commandName].acknowledgement(category);
  } catch (error) {
    console.error("GitHub workflow dispatch failed", {
      command: commandName,
      channelId: interaction.channel_id,
      category,
      error: error instanceof Error ? error.message : String(error),
    });
    content = "Paper Radarの起動に失敗しました。ログを確認してください。";
  }
  try {
    await updateInteraction(interaction, content);
  } catch (error) {
    console.error("Discord acknowledgement update failed", {
      command: commandName,
      channelId: interaction.channel_id,
      category,
      error: error instanceof Error ? error.message : String(error),
    });
  }
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
    const commandName = interaction.data?.name;
    if (interaction.type !== 2 || !COMMANDS[commandName]) {
      return Response.json({ type: 4, data: { content: "Unsupported command.", flags: 64 } });
    }
    let category;
    try {
      category = categoryForChannel(env, interaction.channel_id);
      if (!category) {
        return Response.json({
          type: 4,
          data: {
            content: "このチャンネルにはPaper Radarカテゴリが設定されていません。",
            flags: 64,
          },
        });
      }
      ctx.waitUntil(runCommand(env, interaction, commandName, category));
      return Response.json({ type: 5, data: { flags: 64 } });
    } catch (error) {
      console.error("Paper Radar command failed", {
        command: commandName,
        channelId: interaction.channel_id,
        category,
        error: error instanceof Error ? error.message : String(error),
      });
      return Response.json({
        type: 4,
        data: { content: "Paper Radarの起動に失敗しました。ログを確認してください。", flags: 64 },
      });
    }
  },
};
