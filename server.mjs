import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, isAbsolute, relative, resolve } from "node:path";

const root = resolve(process.cwd());
const port = Number(process.env.PORT || 8080);
const HF_API_TOKEN = process.env.HF_API_TOKEN;
const HF_CHAT_MODEL = "Qwen/Qwen2.5-7B-Instruct:fastest";
const HF_CHAT_URL = "https://router.huggingface.co/v1/chat/completions";

const types = {
  ".html": "text/html;charset=utf-8",
  ".css": "text/css;charset=utf-8",
  ".js": "application/javascript;charset=utf-8",
  ".json": "application/json;charset=utf-8",
  ".webmanifest": "application/manifest+json;charset=utf-8",
  ".svg": "image/svg+xml;charset=utf-8",
};

async function readRequestBody(request) {
  const chunks = [];
  for await (const chunk of request) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf-8");
}

function getLocalSummary(text, templateName) {
  const lines = text.split(/\n+/).filter(Boolean);
  const key = lines.slice(-4).join(" ");

  if (templateName && templateName.startsWith("Social")) {
    return [
      "1) Situation / contexte\n- Rendez-vous de suivi.\n",
      `2) Observations\n- ${key}\n`,
      "3) Besoins / difficultes\n- A preciser : elements concrets, priorites, contraintes.\n",
      "4) Ressources / points d'appui\n- Points positifs mentionnes : a preciser.\n",
      "5) Decisions / accords\n- Accord sur un plan d'action et un prochain contact.\n",
      "6) Plan d'action\n- Action 1 : (responsable) - (echeance)\n- Action 2 : (responsable) - (echeance)\n",
      "7) Prochain suivi\n- A verifier : evolution, documents, points en suspens.\n",
    ].join("\n");
  }

  if (templateName && templateName.startsWith("SOAP")) {
    return [
      `S (Subjectif)\n- ${key}\n`,
      "O (Objectif)\n- Observations factuelles a completer.\n",
      "A (Analyse)\n- Hypotheses/priorites : a preciser.\n",
      "P (Plan)\n- Prochaines etapes : fixer echeances, responsabilites.\n",
    ].join("\n");
  }

  return [
    "Contexte\n- Rendez-vous de suivi.\n",
    `Points cles\n- ${key}\n`,
    "Decisions\n- A preciser.\n",
    "Actions\n- Action 1 : (qui/quoi/quand)\n- Action 2 : (qui/quoi/quand)\n",
    "Suivi\n- Prochain rendez-vous : a planifier.\n",
  ].join("\n");
}

function getInstruction(templateName) {
  if (templateName && templateName.startsWith("Social")) {
    return "Redige une synthese professionnelle : situation, observations, besoins, ressources, decisions, plan d'action et suivi.";
  }

  if (templateName && templateName.startsWith("SOAP")) {
    return "Convertis la transcription en note SOAP : subjectif, objectif, analyse et plan.";
  }

  return "Transforme la transcription en compte-rendu structure : contexte, points cles, decisions, actions et suivi.";
}

function buildHfMessages(text, templateName) {
  return [
    {
      role: "system",
      content:
        "Tu es un assistant professionnel specialise dans la redaction de comptes-rendus en francais. Sois concis, structure, utilise des tirets pour les listes.",
    },
    {
      role: "user",
      content: `${getInstruction(templateName)}\n\nTranscription :\n${text}`,
    },
  ];
}

function parseHfChatResponse(data) {
  return String(data?.choices?.[0]?.message?.content || data?.choices?.[0]?.text || "").trim();
}

async function summarizeWithHuggingFace(text, templateName, token) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 45_000);
  try {
    const response = await fetch(HF_CHAT_URL, {
      signal: controller.signal,
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: HF_CHAT_MODEL,
        messages: buildHfMessages(text, templateName),
        max_tokens: 600,
        temperature: 0.2,
      }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Hugging Face error ${response.status}: ${errorText}`);
    }

    const data = await response.json();
    return parseHfChatResponse(data);
  } finally {
    clearTimeout(timeout);
  }
}

createServer(async (request, response) => {
  try {
    const url = new URL(request.url || "/", `http://${request.headers.host}`);

    if (url.pathname === "/api/summarize" && request.method === "POST") {
      const rawBody = await readRequestBody(request);
      let payload;
      try {
        payload = JSON.parse(rawBody);
      } catch {
        response.writeHead(400, { "content-type": "application/json;charset=utf-8" });
        response.end(JSON.stringify({ error: "Corrupted JSON payload." }));
        return;
      }

      const text = String(payload.text || "").trim();
      const templateName = String(payload.templateName || "");
      const requestToken = String(payload.hfToken || "").trim();
      const hfToken = requestToken || HF_API_TOKEN;
      if (!text) {
        response.writeHead(400, { "content-type": "application/json;charset=utf-8" });
        response.end(JSON.stringify({ error: "Text is required." }));
        return;
      }

      let summary;
      let source = "local";
      if (hfToken) {
        try {
          summary = await summarizeWithHuggingFace(text, templateName, hfToken);
          source = "huggingface";
        } catch (error) {
          console.error(error);
          summary = getLocalSummary(text, templateName);
        }
      } else {
        summary = getLocalSummary(text, templateName);
      }

      response.writeHead(200, { "content-type": "application/json;charset=utf-8" });
      response.end(JSON.stringify({ summary, source }));
      return;
    }

    const requestedPath = url.pathname === "/" ? "index.html" : decodeURIComponent(url.pathname.slice(1));
    const filePath = resolve(root, requestedPath);
    const relativePath = relative(root, filePath);

    if (relativePath.startsWith("..") || isAbsolute(relativePath)) {
      response.writeHead(403);
      response.end("Forbidden");
      return;
    }

    const body = await readFile(filePath);
    response.writeHead(200, {
      "content-type": types[extname(filePath)] || "application/octet-stream",
    });
    response.end(body);
  } catch (error) {
    console.error(error);
    response.writeHead(404);
    response.end("Not found");
  }
}).listen(port, "127.0.0.1", () => {
  console.log(`Nautes local server: http://127.0.0.1:${port}`);
  if (!HF_API_TOKEN) {
    console.log("No Hugging Face API token found. Summarization will use local fallback.");
  }
});
