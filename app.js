const TEMPLATES = {
  "Compte-rendu (simple)": {
    user:
      "Transforme la transcription en compte-rendu structure : contexte, points cles, decisions, actions et suivi.",
  },
  "Social / educatif (synthese)": {
    user:
      "Redige une synthese professionnelle : situation, observations, besoins, ressources, decisions, plan d'action et suivi.",
  },
  "SOAP (sante/psy)": {
    user: "Convertis la transcription en note SOAP : subjectif, objectif, analyse et plan.",
  },
};

const STORAGE_KEYS = {
  settings: "nautes.settings.v1",
  notes: "nautes.notes.v1",
  draft: "nautes.draft.v1",
};

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const supportsSpeechRecognition = !!SpeechRecognition;

const state = {
  title: `Rendez-vous - ${new Date().toLocaleDateString("fr-BE")}`,
  templateName: "Social / educatif (synthese)",
  language: "fr-FR",
  debug: false,
  keepAudio: false,
  consent: false,
  storageMode: "offline",
  useSpeechRecognition: true,
  hfToken: "",
  updateReady: false,
  isRecording: false,
  elapsed: 0,
  transcript: "",
  summary: "",
  mediaRecorder: null,
  speechRecognition: null,
  chunks: [],
  timer: null,
  startTime: 0,
};

const els = {};
let waitingServiceWorker = null;
let refreshingServiceWorker = false;

document.addEventListener("DOMContentLoaded", () => {
  bindElements();
  loadSettings();
  loadDraft();
  fillTemplateSelect();
  bindEvents();
  checkEnvironment();
  render();
  registerServiceWorker();
});

function bindElements() {
  [
    "settingsButton",
    "closeSettingsButton",
    "settingsPanel",
    "recordButton",
    "recordIcon",
    "recordLabel",
    "timer",
    "statusText",
    "updateButton",
    "resultPanel",
    "transcriptText",
    "summaryText",
    "regenerateButton",
    "copyButton",
    "saveCurrentButton",
    "titleInput",
    "languageSelect",
    "templateSelect",
    "debugSwitch",
    "keepAudioSwitch",
    "speechRecognitionSwitch",
    "consentSwitch",
    "storageModeSelect",
    "historyList",
    "clearHistoryButton",
    "downloadButton",
    "shareButton",
    "clearButton",
    "hfTokenInput",
  ].forEach((id) => {
    els[id] = document.getElementById(id);
  });
}

function bindEvents() {
  els.recordButton.addEventListener("click", () => {
    if (state.isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  });

  els.settingsButton.addEventListener("click", () => toggleSettings(true));
  els.closeSettingsButton.addEventListener("click", () => toggleSettings(false));
  els.settingsPanel.addEventListener("click", (event) => {
    if (event.target === els.settingsPanel) toggleSettings(false);
  });

  document.querySelectorAll(".tab-button").forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.tab));
  });

  els.titleInput.addEventListener("input", () => {
    state.title = els.titleInput.value;
    persistSettings();
    persistDraft();
  });
  els.languageSelect.addEventListener("change", () => {
    state.language = els.languageSelect.value;
    persistSettings();
  });
  els.templateSelect.addEventListener("change", () => {
    state.templateName = els.templateSelect.value;
    persistSettings();
  });
  els.debugSwitch.addEventListener("change", () => {
    state.debug = els.debugSwitch.checked;
    if (!state.debug) state.keepAudio = false;
    persistSettings();
    render();
  });
  els.keepAudioSwitch.addEventListener("change", () => {
    state.keepAudio = els.keepAudioSwitch.checked;
    persistSettings();
  });
  els.speechRecognitionSwitch.addEventListener("change", () => {
    state.useSpeechRecognition = els.speechRecognitionSwitch.checked;
    persistSettings();
  });
  els.consentSwitch.addEventListener("change", () => {
    state.consent = els.consentSwitch.checked;
    persistSettings();
  });
  els.storageModeSelect.addEventListener("change", () => {
    state.storageMode = els.storageModeSelect.value;
    persistSettings();
  });
  els.hfTokenInput.addEventListener("input", () => {
    state.hfToken = els.hfTokenInput.value.trim();
    persistSettings();
  });

  els.transcriptText.addEventListener("input", () => {
    state.transcript = els.transcriptText.value;
    persistDraft();
  });
  els.summaryText.addEventListener("input", () => {
    state.summary = els.summaryText.value;
    persistDraft();
  });

  els.regenerateButton.addEventListener("click", regenerateSummary);
  els.copyButton.addEventListener("click", copyCurrentNote);
  els.saveCurrentButton.addEventListener("click", saveCurrentNote);
  els.downloadButton.addEventListener("click", downloadCurrentNote);
  els.shareButton.addEventListener("click", shareCurrentNote);
  els.updateButton.addEventListener("click", () => {
    if (waitingServiceWorker) {
      waitingServiceWorker.postMessage({ type: "SKIP_WAITING" });
    } else {
      window.location.reload();
    }
  });
  els.clearButton.addEventListener("click", clearDraft);
  els.clearHistoryButton.addEventListener("click", clearHistory);
}

async function startRecording() {
  if (state.useSpeechRecognition && supportsSpeechRecognition) {
    return startSpeechRecognition();
  }

  try {
    state.summary = "";
    setStatus("Demande d'acces micro...");

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = pickMimeType();
    const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);

    state.mediaRecorder = recorder;
    state.chunks = [];

    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) state.chunks.push(event.data);
    };

    recorder.onstop = async () => {
      setStatus("Transcription...");
      const blob = new Blob(state.chunks, { type: recorder.mimeType || "audio/webm" });
      const text = await fakeTranscribe(blob, state.language);
      state.transcript = state.transcript ? `${state.transcript}\n${text}` : text;

      if (!state.keepAudio) state.chunks = [];
      stream.getTracks().forEach((track) => track.stop());

      setStatus("Generation IA...");
      state.summary = await summarizeText(state.transcript, state.templateName);
      persistDraft();
      saveCurrentNote({ quiet: true });
      setStatus("Compte-rendu pret");
      render();
    };

    recorder.start(250);
    state.startTime = Date.now();
    state.elapsed = 0;
    state.timer = window.setInterval(() => {
      state.elapsed = Date.now() - state.startTime;
      renderTimer();
    }, 250);

    state.isRecording = true;
    setStatus("Enregistrement audio...");
    render();
  } catch (error) {
    setStatus(`Erreur micro : ${error?.message || error}`);
  }
}

function startSpeechRecognition() {
  try {
    state.summary = "";
    setStatus("Demande d'acces micro et reconnaissance vocale...");

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.lang = state.language;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .slice(event.resultIndex)
        .map((result) => result[0].transcript)
        .join(" ");

      state.transcript = state.transcript ? `${state.transcript}\n${transcript}` : transcript;
      persistDraft();
      render();
    };

    recognition.onerror = (event) => {
      setStatus(`Erreur reconnaissance vocale : ${event.error || event.message || "inconnue"}`);
      stopSpeechRecognition();
    };

    recognition.onend = async () => {
      state.isRecording = false;
      state.speechRecognition = null;
      setStatus("Traitement de la transcription...");
      if (state.transcript.trim()) {
        state.summary = await summarizeText(state.transcript, state.templateName);
        persistDraft();
        saveCurrentNote({ quiet: true });
        setStatus("Compte-rendu pret");
      } else {
        setStatus("Aucune transcription recue.");
      }
      render();
    };

    recognition.start();
    state.speechRecognition = recognition;
    state.isRecording = true;
    state.startTime = Date.now();
    state.elapsed = 0;
    state.timer = window.setInterval(() => {
      state.elapsed = Date.now() - state.startTime;
      renderTimer();
    }, 250);

    setStatus("Enregistrement et transcription en cours...");
    render();
  } catch (error) {
    setStatus(`Erreur reconnaissance vocale : ${error?.message || error}`);
  }
}

function stopRecording() {
  try {
    window.clearInterval(state.timer);
    state.timer = null;
    state.elapsed = 0;
    state.isRecording = false;

    if (state.speechRecognition) {
      stopSpeechRecognition();
    } else if (state.mediaRecorder && state.mediaRecorder.state !== "inactive") {
      state.mediaRecorder.stop();
    }
    render();
  } catch (error) {
    setStatus(`Erreur stop : ${error?.message || error}`);
  }
}

function stopSpeechRecognition() {
  if (!state.speechRecognition) return;
  try {
    state.speechRecognition.stop();
  } catch {
    // ignore stop errors
  }
  state.speechRecognition = null;
}

function pickMimeType() {
  if (window.MediaRecorder?.isTypeSupported?.("audio/webm")) return "audio/webm";
  if (window.MediaRecorder?.isTypeSupported?.("audio/mp4")) return "audio/mp4";
  return "";
}

async function regenerateSummary() {
  if (!state.transcript.trim()) return;
  setStatus("Generation IA...");
  state.summary = await summarizeText(state.transcript, state.templateName);
  persistDraft();
  saveCurrentNote({ quiet: true });
  setStatus("Compte-rendu pret");
  render();
}

async function summarizeText(text, templateName) {
  if (state.hfToken) {
    try {
      setStatus("Analyse IA en cours…");
      return await summarizeWithHF(text, templateName, state.hfToken);
    } catch (error) {
      console.warn("HF API failed, using local fallback:", error);
      setStatus("IA indisponible, résumé local utilisé.");
    }
  }
  return fakeSummarize(text, templateName);
}

async function summarizeWithHF(text, templateName, token) {
  const template = TEMPLATES[templateName];
  const instruction = template?.user ?? "Fais un compte-rendu structuré de cette transcription en français.";

  const response = await fetch(
    "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.3/v1/chat/completions",
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "mistralai/Mistral-7B-Instruct-v0.3",
        messages: [
          {
            role: "system",
            content:
              "Tu es un assistant professionnel spécialisé dans la rédaction de comptes-rendus en français. Sois concis, structuré et utilise des tirets pour les listes.",
          },
          {
            role: "user",
            content: `${instruction}\n\nTranscription :\n${text}`,
          },
        ],
        max_tokens: 600,
        temperature: 0.2,
      }),
    }
  );

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`HF ${response.status}: ${err}`);
  }

  const data = await response.json();
  return data.choices?.[0]?.message?.content ?? "";
}

async function copyCurrentNote() {
  const text = buildExportText();
  if (!text.trim()) return;
  await navigator.clipboard.writeText(text);
  setStatus("Copie dans le presse-papiers");
}

function saveCurrentNote(options = {}) {
  if (!state.transcript.trim() && !state.summary.trim()) return;
  const notes = getNotes();
  const now = new Date().toISOString();
  const existingIndex = notes.findIndex((note) => note.id === getDraftId());
  const note = {
    id: getDraftId(),
    title: state.title || "Note sans titre",
    createdAt: existingIndex >= 0 ? notes[existingIndex].createdAt : now,
    updatedAt: now,
    language: state.language,
    templateName: state.templateName,
    transcript: state.transcript,
    summary: state.summary,
  };

  if (existingIndex >= 0) {
    notes[existingIndex] = note;
  } else {
    notes.unshift(note);
  }

  localStorage.setItem(STORAGE_KEYS.notes, JSON.stringify(notes.slice(0, 100)));
  if (!options.quiet) setStatus("Note sauvee en memoire interne");
  renderHistory();
}

function downloadCurrentNote() {
  const html = buildWordExportHtml();
  if (!html.trim()) return;
  const blob = new Blob([html], { type: "application/msword;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${sanitizeFileName(state.title)}.doc`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function buildWordExportHtml() {
  if (!state.transcript.trim() && !state.summary.trim()) return "";
  return `<!DOCTYPE html>
<html lang="fr">
  <head>
    <meta charset="UTF-8" />
    <title>${escapeHtml(state.title)}</title>
  </head>
  <body>
    <h1>${escapeHtml(state.title)}</h1>
    <h2>Transcription</h2>
    <pre>${escapeHtml(state.transcript)}</pre>
    <h2>Compte-rendu IA</h2>
    <pre>${escapeHtml(state.summary || "(non genere)")}</pre>
  </body>
</html>`;
}

async function shareCurrentNote() {
  const text = buildExportText();
  if (!text.trim()) return;

  if (navigator.share) {
    await navigator.share({ title: state.title, text });
  } else {
    await navigator.clipboard.writeText(text);
    setStatus("Partage indisponible, texte copie");
  }
}

function clearDraft() {
  state.transcript = "";
  state.summary = "";
  state.chunks = [];
  localStorage.removeItem(STORAGE_KEYS.draft);
  setStatus("Note courante effacee");
  render();
}

function clearHistory() {
  const ok = window.confirm("Vider l'historique local de ce telephone ?");
  if (!ok) return;
  localStorage.removeItem(STORAGE_KEYS.notes);
  renderHistory();
}

function loadNote(id) {
  const note = getNotes().find((item) => item.id === id);
  if (!note) return;
  state.title = note.title;
  state.language = note.language;
  state.templateName = note.templateName;
  state.transcript = note.transcript;
  state.summary = note.summary;
  localStorage.setItem(STORAGE_KEYS.draft, JSON.stringify({ ...note, draftId: note.id }));
  toggleSettings(false);
  setStatus("Note chargee");
  render();
}

function render() {
  els.recordButton.classList.toggle("recording", state.isRecording);
  els.recordLabel.textContent = state.isRecording ? "Stop" : "Demarrer";
  els.timer.hidden = !state.isRecording;
  renderTimer();

  const hasResult = Boolean(state.transcript.trim() || state.summary.trim());
  els.resultPanel.hidden = !hasResult;
  els.transcriptText.value = state.transcript;
  els.summaryText.value = state.summary;

  els.titleInput.value = state.title;
  els.languageSelect.value = state.language;
  els.templateSelect.value = state.templateName;
  els.debugSwitch.checked = state.debug;
  els.keepAudioSwitch.checked = state.keepAudio;
  els.keepAudioSwitch.disabled = !state.debug;
  els.speechRecognitionSwitch.checked = state.useSpeechRecognition;
  els.consentSwitch.checked = state.consent;
  els.storageModeSelect.value = state.storageMode;
  if (document.activeElement !== els.hfTokenInput) {
    els.hfTokenInput.value = state.hfToken;
  }
  els.updateButton.hidden = !state.updateReady;

  renderHistory();
}

function renderTimer() {
  els.timer.textContent = formatDuration(state.elapsed);
}

function renderHistory() {
  const notes = getNotes();
  els.historyList.innerHTML = "";

  if (!notes.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Aucune note locale pour le moment.";
    els.historyList.appendChild(empty);
    return;
  }

  notes.forEach((note) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "history-item";
    button.innerHTML = `<strong>${escapeHtml(note.title)}</strong><small>${formatDate(note.updatedAt)} · ${escapeHtml(note.templateName)}</small>`;
    button.addEventListener("click", () => loadNote(note.id));
    els.historyList.appendChild(button);
  });
}

function fillTemplateSelect() {
  els.templateSelect.innerHTML = "";
  Object.keys(TEMPLATES).forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    els.templateSelect.appendChild(option);
  });
}

function activateTab(name) {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === name);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.panel === name);
  });
}

function checkEnvironment() {
  const fileProtocol = location.protocol === "file:";
  const noMicro = !navigator.mediaDevices?.getUserMedia;

  if (fileProtocol) {
    setStatus("Ouvrez l'application via http://localhost ou un serveur local pour activer le micro.");
    els.recordButton.disabled = true;
    els.speechRecognitionSwitch.disabled = true;
    return;
  }

  if (noMicro) {
    setStatus("Micro indisponible dans ce navigateur.");
    els.recordButton.disabled = true;
    els.speechRecognitionSwitch.disabled = true;
    return;
  }

  if (!supportsSpeechRecognition) {
    els.speechRecognitionSwitch.disabled = true;
    if (state.useSpeechRecognition) {
      state.useSpeechRecognition = false;
      persistSettings();
    }
    setStatus("Reconnaissance vocale gratuite indisponible dans ce navigateur. L'enregistrement audio reste utilisable.");
  }

  els.recordButton.disabled = false;
}

function toggleSettings(open) {
  els.settingsPanel.hidden = !open;
}

function promptUpdate(worker) {
  waitingServiceWorker = worker;
  state.updateReady = true;
  setStatus("Nouvelle version disponible. Cliquez sur Recharger pour mettre à jour.");
  render();
}

function setStatus(text) {
  els.statusText.textContent = text;
}

function loadSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEYS.settings) || "{}");
    Object.assign(state, saved);
  } catch {
    persistSettings();
  }
}

function persistSettings() {
  const settings = {
    title: state.title,
    templateName: state.templateName,
    language: state.language,
    debug: state.debug,
    keepAudio: state.keepAudio,
    useSpeechRecognition: state.useSpeechRecognition,
    consent: state.consent,
    storageMode: state.storageMode,
    hfToken: state.hfToken,
  };
  localStorage.setItem(STORAGE_KEYS.settings, JSON.stringify(settings));
}

function loadDraft() {
  try {
    const draft = JSON.parse(localStorage.getItem(STORAGE_KEYS.draft) || "{}");
    if (draft.title) state.title = draft.title;
    if (draft.transcript) state.transcript = draft.transcript;
    if (draft.summary) state.summary = draft.summary;
  } catch {
    localStorage.removeItem(STORAGE_KEYS.draft);
  }
}

function persistDraft() {
  localStorage.setItem(
    STORAGE_KEYS.draft,
    JSON.stringify({
      draftId: getDraftId(),
      title: state.title,
      transcript: state.transcript,
      summary: state.summary,
    }),
  );
}

function getDraftId() {
  try {
    const draft = JSON.parse(localStorage.getItem(STORAGE_KEYS.draft) || "{}");
    if (draft.draftId) return draft.draftId;
  } catch {
    // A corrupted draft simply receives a new local id.
  }
  const id = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
  const draft = { draftId: id, title: state.title, transcript: state.transcript, summary: state.summary };
  localStorage.setItem(STORAGE_KEYS.draft, JSON.stringify(draft));
  return id;
}

function getNotes() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEYS.notes) || "[]");
  } catch {
    return [];
  }
}

function buildExportText() {
  if (!state.transcript.trim() && !state.summary.trim()) return "";
  return `# ${state.title}\n\n## Transcription\n${state.transcript}\n\n---\n\n## Compte-rendu IA\n${state.summary || "(non genere)"}\n`;
}

function formatDuration(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

function formatDate(value) {
  return new Intl.DateTimeFormat("fr-BE", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

function sanitizeFileName(value) {
  return (value || "note").replace(/[^a-zA-Z0-9-_ ]/g, "").slice(0, 60) || "note";
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };
    return map[char];
  });
}

async function fakeTranscribe(blob, language) {
  await sleep(650);
  const kb = Math.max(1, Math.round(blob.size / 1024));
  const samples = [
    "Bonjour, on fait un point sur la situation et les etapes suivantes.",
    "La famille exprime des difficultes sur l'organisation et la communication.",
    "Decision : planifier un suivi dans deux semaines et clarifier les responsabilites.",
    "Action : envoyer la liste des documents necessaires et fixer le prochain rendez-vous.",
  ];
  const pick = samples[Math.floor(Math.random() * samples.length)];
  return `(${language}, ~${kb}KB) ${pick}`;
}

async function fakeSummarize(text, templateName) {
  await sleep(700);
  if (!text.trim()) return "";
  const lines = text.split(/\n+/).filter(Boolean);
  const key = lines.slice(-4).join(" ");

  if (templateName.startsWith("Social")) {
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

  if (templateName.startsWith("SOAP")) {
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

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  if (location.protocol === "file:") return;

  navigator.serviceWorker.register("./sw.js").then((registration) => {
    if (registration.waiting) {
      promptUpdate(registration.waiting);
    }

    registration.addEventListener("updatefound", () => {
      const newWorker = registration.installing;
      if (!newWorker) return;

      newWorker.addEventListener("statechange", () => {
        if (newWorker.state === "installed" && navigator.serviceWorker.controller) {
          promptUpdate(newWorker);
        }
      });
    });
  });

  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (refreshingServiceWorker) return;
    refreshingServiceWorker = true;
    window.location.reload();
  });
}
