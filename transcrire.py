"""Transcription audio mot a mot, en local, sans limite de duree."""

import os
import queue
import sys
import tarfile
import threading
import time
import tkinter as tk
import urllib.request
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

AUDIO_TYPES = [
    ("Fichiers audio et video", "*.mp3 *.m4a *.wav *.flac *.ogg *.opus *.aac *.wma *.mp4 *.mov *.avi *.mkv"),
    ("Tous les fichiers", "*.*"),
]

DIARIZATION_SEGMENTATION_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/"
    "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
)
# "recongition" est une faute de frappe dans le nom de la release amont : ne pas la corriger.
DIARIZATION_EMBEDDING_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
    "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
)
# Seuil utilise seulement quand le nombre d'interlocuteurs n'est pas connu.
# Mesure sur une conversation reelle de 10 min a 2 voix : ce mode fragmente une meme
# personne en une quinzaine de voix. Indiquer le nombre exact est nettement plus fiable,
# d'ou le choix de "2 personnes" par defaut.
DIARIZATION_THRESHOLD = 0.7
# Une voix qui totalise moins que ces deux seuils est consideree comme un artefact
# et rendue a la voix voisine. Valeurs mesurees : plus severes (0.08 / 5 s), elles
# fusionnaient deux personnes reelles en une seule.
MARGINAL_SPEAKER_SHARE = 0.05
MARGINAL_SPEAKER_SECONDS = 3.0
SAMPLE_RATE = 16_000
# L'interface ne se rafraichit qu'a cet intervalle : sur un fichier de 2 h, un
# rafraichissement par segment sature la fenetre et Windows la declare "Ne repond pas".
UI_REFRESH_SECONDS = 0.3
# L'apercu ne garde que la fin du texte, sinon son cout de rendu croit sans limite.
PREVIEW_MAX_LINES = 250

SPEAKER_COUNTS = {
    "2 personnes": 2,
    "3 personnes": 3,
    "4 personnes": 4,
    "5 personnes": 5,
    "6 personnes": 6,
    "8 personnes": 8,
    "10 personnes": 10,
    "Je ne sais pas": 0,
}

MODELS = {
    "Rapide (small)": "small",
    "Equilibre (medium)": "medium",
    "Meilleure qualite (large-v3)": "large-v3",
}

LANGUAGES = {
    "Francais": "fr",
    "Anglais": "en",
    "Neerlandais": "nl",
    "Allemand": "de",
    "Espagnol": "es",
    "Italien": "it",
    "Detection automatique": None,
}


def format_clock(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def format_duration(seconds: float) -> str:
    minutes = max(1, int(round(seconds / 60)))
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d}"


def format_srt_time(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def build_paragraphs(segments, gap: float = 1.6) -> str:
    """Regroupe les segments en paragraphes, en coupant sur les silences."""
    paragraphs: list[list[str]] = []
    current: list[str] = []
    previous_end = None

    for start, end, text, _speaker in segments:
        if previous_end is not None and start - previous_end > gap and current:
            paragraphs.append(current)
            current = []
        current.append(text)
        previous_end = end

    if current:
        paragraphs.append(current)

    return "\n\n".join(" ".join(part).strip() for part in paragraphs)


def speaker_label(index) -> str:
    return "Interlocuteur ?" if index is None else f"Interlocuteur {index + 1}"


def build_speaker_paragraphs(segments) -> str:
    """Regroupe les segments en repliques, en coupant a chaque changement de voix."""
    blocks: list[tuple[object, list[str]]] = []
    current: list[str] = []
    current_speaker: object = object()  # sentinelle, distincte de None

    for _start, _end, text, speaker in segments:
        if current and speaker != current_speaker:
            blocks.append((current_speaker, current))
            current = []
        current_speaker = speaker
        current.append(text)

    if current:
        blocks.append((current_speaker, current))

    return "\n\n".join(f"{speaker_label(spk)} : {' '.join(parts).strip()}" for spk, parts in blocks)


def assign_speakers(segments, turns):
    """Attribue a chaque segment transcrit la voix qui le recouvre le plus longtemps.

    Les identifiants renvoyes par la diarisation ne sont ni continus ni ordonnes ;
    ils sont renumerotes ici selon l'ordre d'apparition, pour donner
    "Interlocuteur 1" a la premiere personne qui parle.
    """
    if not turns:
        return [(start, end, text, None) for start, end, text in segments]

    order: dict[int, int] = {}
    assigned = []
    previous = None

    for start, end, text in segments:
        best_speaker = None
        best_overlap = 0.0
        for turn_start, turn_end, speaker in turns:
            overlap = min(end, turn_end) - max(start, turn_start)
            if overlap > best_overlap:
                best_speaker, best_overlap = speaker, overlap

        # Segment sans recouvrement (chuchotement, bruit) : on prolonge la voix precedente.
        if best_speaker is None:
            best_speaker = previous
        else:
            previous = best_speaker

        if best_speaker is not None and best_speaker not in order:
            order[best_speaker] = len(order)

        assigned.append((start, end, text, None if best_speaker is None else order[best_speaker]))

    return assigned


def models_dir() -> Path:
    base = os.getenv("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".cache"
    directory = root / "TranscriptionAudio" / "modeles"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def download_file(url: str, destination: Path, emit, label: str) -> None:
    partial = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "TranscriptionAudio"})

    with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        while True:
            chunk = response.read(262_144)
            if not chunk:
                break
            handle.write(chunk)
            received += len(chunk)
            if total:
                emit("status", text=f"Telechargement {label} : {received * 100 // total} %")
                emit("progress", value=received / total * 100)

    partial.replace(destination)


def ensure_diarization_models(emit) -> tuple[Path, Path]:
    """Telecharge au premier usage les deux modeles d'identification des voix (37 Mo)."""
    directory = models_dir()
    segmentation = directory / "segmentation.onnx"
    embedding = directory / "empreinte_vocale.onnx"

    if not segmentation.exists():
        archive = directory / "segmentation.tar.bz2"
        download_file(DIARIZATION_SEGMENTATION_URL, archive, emit, "du modele de decoupage (7 Mo)")
        with tarfile.open(archive, "r:bz2") as tar:
            member = next(
                (item for item in tar.getmembers() if item.name.endswith("segmentation-3-0/model.onnx")),
                None,
            )
            extracted = tar.extractfile(member) if member else None
            if extracted is None:
                raise RuntimeError("Archive du modele de decoupage illisible.")
            segmentation.write_bytes(extracted.read())
        archive.unlink(missing_ok=True)

    if not embedding.exists():
        download_file(DIARIZATION_EMBEDDING_URL, embedding, emit, "du modele de voix (28 Mo)")

    return segmentation, embedding


def merge_marginal_speakers(turns):
    """Rend a la voix voisine les grappes trop petites pour etre une vraie personne.

    Sans nombre d'interlocuteurs impose, le regroupement automatique eclate une meme
    personne en de nombreuses voix des que le micro bouge ou que l'intonation change.
    Les grappes qui ne representent qu'une part negligeable de la parole sont donc
    reattribuees a la voix retenue la plus proche dans le temps.
    """
    if not turns:
        return turns

    totals: dict[int, float] = {}
    for start, end, speaker in turns:
        totals[speaker] = totals.get(speaker, 0.0) + max(0.0, end - start)

    overall = sum(totals.values())
    if overall <= 0:
        return turns

    kept = {
        speaker
        for speaker, spoken in totals.items()
        if spoken >= MARGINAL_SPEAKER_SECONDS and spoken / overall >= MARGINAL_SPEAKER_SHARE
    }
    if not kept:
        kept = {max(totals, key=totals.get)}
    if len(kept) == len(totals):
        return turns

    cleaned = []
    for start, end, speaker in turns:
        if speaker in kept:
            cleaned.append((start, end, speaker))
            continue
        nearest, smallest_gap = None, None
        for other_start, other_end, other in turns:
            if other not in kept:
                continue
            overlapping = other_start < end and start < other_end
            gap = 0.0 if overlapping else min(abs(start - other_end), abs(other_start - end))
            if smallest_gap is None or gap < smallest_gap:
                nearest, smallest_gap = other, gap
        cleaned.append((start, end, speaker if nearest is None else nearest))

    return cleaned


def build_diarizer(segmentation: Path, embedding: Path, expected_count: int):
    try:
        import sherpa_onnx
    except ImportError as error:
        raise RuntimeError(
            "Le composant d'identification des interlocuteurs n'est pas installe.\n"
            "Relancez Installer.bat pour l'ajouter."
        ) from error

    threads = max(1, (os.cpu_count() or 4) - 1)
    clustering = (
        sherpa_onnx.FastClusteringConfig(num_clusters=expected_count)
        if expected_count >= 2
        else sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=DIARIZATION_THRESHOLD)
    )
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(segmentation)),
            num_threads=threads,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(embedding), num_threads=threads),
        clustering=clustering,
        min_duration_on=0.3,
        min_duration_off=0.5,
    )

    if not config.validate():
        raise RuntimeError("Configuration d'identification des interlocuteurs invalide.")

    return sherpa_onnx.OfflineSpeakerDiarization(config)


class Transcriber(threading.Thread):
    """Transcrit une liste de fichiers dans un thread, en publiant sa progression."""

    def __init__(self, files, options, events):
        super().__init__(daemon=True)
        self.files = files
        self.options = options
        self.events = events
        self.cancelled = threading.Event()

    def emit(self, kind, **payload):
        self.events.put({"kind": kind, **payload})

    def lower_priority(self):
        """Laisse la fenetre passer devant le calcul.

        Sans cela, les threads de transcription monopolisent le processeur et Windows
        finit par afficher "Ne repond pas" alors que le travail avance normalement.
        """
        if sys.platform != "win32":
            return
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            below_normal = -1
            kernel32.SetThreadPriority(kernel32.GetCurrentThread(), below_normal)
        except Exception:  # noqa: BLE001 - priorite non reglable, sans consequence
            pass

    def run(self):
        self.lower_priority()
        try:
            model = self.load_model()
        except Exception as error:  # noqa: BLE001 - remonte tel quel a l'interface
            self.emit("failed", message=str(error))
            return

        written = []
        for index, path in enumerate(self.files, start=1):
            if self.cancelled.is_set():
                break
            try:
                written.extend(self.transcribe_one(model, Path(path), index))
            except Exception as error:  # noqa: BLE001
                self.emit("failed", message=f"{Path(path).name} : {error}")
                return

        if self.cancelled.is_set():
            self.emit("cancelled")
        else:
            self.emit("done", outputs=written)

    def load_model(self):
        from faster_whisper import WhisperModel

        name = self.options["model"]
        self.emit("status", text=f"Chargement du modele {name} (telechargement au premier usage)...")

        if self.options["use_gpu"]:
            try:
                return WhisperModel(name, device="cuda", compute_type="float16")
            except Exception:  # noqa: BLE001 - pas de GPU utilisable, on continue en CPU
                self.emit("status", text="GPU indisponible, bascule sur le processeur...")

        threads = max(1, (os.cpu_count() or 4) - 1)
        return WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=threads)

    def detect_speakers(self, audio, path: Path, index: int):
        total = len(self.files)
        self.emit("status", text=f"[{index}/{total}] Preparation de l'identification des interlocuteurs...")
        segmentation, embedding = ensure_diarization_models(self.emit)
        expected = self.options["speaker_count"]
        diarizer = build_diarizer(segmentation, embedding, expected)

        started = time.monotonic()
        last_refresh = 0.0

        def report(processed, chunks):
            nonlocal last_refresh
            if self.cancelled.is_set():
                return 1
            # Meme precaution que pour la transcription : sur un fichier de 2 h, cette
            # fonction est appelee des milliers de fois et noierait la fenetre.
            now = time.monotonic()
            if chunks and now - last_refresh >= UI_REFRESH_SECONDS:
                last_refresh = now
                self.emit("progress", value=processed / chunks * 100)
                line = f"[{index}/{total}] Identification des interlocuteurs : {processed * 100 // chunks} %"
                if processed > 20 and now - started > 20:
                    remaining = (now - started) * (chunks - processed) / processed
                    line += f"  ·  encore ~{format_duration(remaining)}"
                self.emit("status", text=line)
            return 0

        result = diarizer.process(audio, callback=report)
        if self.cancelled.is_set():
            return []

        turns = [(item.start, item.end, item.speaker) for item in result.sort_by_start_time()]
        if expected < 2:
            turns = merge_marginal_speakers(turns)

        count = len({speaker for _start, _end, speaker in turns})
        self.emit("status", text=f"[{index}/{total}] {count} interlocuteur(s) detecte(s).")
        self.emit("progress", value=0)
        return turns

    def transcribe_one(self, model, path: Path, index: int):
        total = len(self.files)
        self.emit("status", text=f"[{index}/{total}] Analyse de {path.name}...")
        self.emit("progress", value=0)

        source = str(path)
        turns = []

        if self.options["with_speakers"]:
            from faster_whisper.audio import decode_audio

            # Decode une seule fois : le meme tableau sert a la diarisation et a la transcription.
            self.emit("status", text=f"[{index}/{total}] Lecture de {path.name}...")
            source = decode_audio(str(path), sampling_rate=SAMPLE_RATE)
            turns = self.detect_speakers(source, path, index)
            if self.cancelled.is_set():
                return []

        segments, info = model.transcribe(
            source,
            language=self.options["language"],
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,
        )

        duration = info.duration or 0
        collected = []
        started = time.monotonic()
        last_refresh = 0.0

        # Sur un fichier de 2 h, le calcul dure des heures : le texte est ecrit au fur
        # et a mesure pour qu'une coupure n'efface jamais le travail deja fait.
        rescue = path.with_name(f"{path.stem}_en_cours.txt")
        handle = rescue.open("w", encoding="utf-8")

        try:
            for segment in segments:
                if self.cancelled.is_set():
                    return []
                text = segment.text.strip()
                if text:
                    collected.append((segment.start, segment.end, text))
                    handle.write(text + "\n")
                    handle.flush()
                    self.emit("line", text=text)

                now = time.monotonic()
                if now - last_refresh >= UI_REFRESH_SECONDS:
                    last_refresh = now
                    if duration:
                        self.emit("progress", value=min(100, segment.end / duration * 100))
                    self.emit(
                        "status",
                        text=self.progress_text(index, total, path, segment.end, duration, now - started),
                    )
        finally:
            handle.close()

        written = self.write_outputs(path, assign_speakers(collected, turns))
        rescue.unlink(missing_ok=True)
        return written

    def progress_text(self, index, total, path: Path, position, duration, elapsed):
        line = f"[{index}/{total}] {path.name} — {format_clock(position)} / {format_clock(duration)}"
        if duration and position > 60 and elapsed > 20:
            remaining = elapsed * (duration - position) / position
            line += f"  ·  encore ~{format_duration(remaining)}"
        return line

    def write_outputs(self, path: Path, collected):
        written = []
        # Si la diarisation n'a rien trouve, on retombe sur la mise en forme sans locuteurs.
        with_speakers = any(speaker is not None for _start, _end, _text, speaker in collected)

        def prefixed(text, speaker):
            return f"{speaker_label(speaker)} : {text}" if with_speakers else text

        text_path = path.with_suffix(".txt")
        body = build_speaker_paragraphs(collected) if with_speakers else build_paragraphs(collected)
        text_path.write_text(body + "\n", encoding="utf-8")
        written.append(text_path)

        if self.options["with_timestamps"]:
            stamped = "\n".join(
                f"[{format_clock(start)}] {prefixed(text, speaker)}"
                for start, _end, text, speaker in collected
            )
            stamped_path = path.with_name(f"{path.stem}_horodate.txt")
            stamped_path.write_text(stamped + "\n", encoding="utf-8")
            written.append(stamped_path)

        if self.options["with_srt"]:
            blocks = [
                f"{position}\n{format_srt_time(start)} --> {format_srt_time(end)}\n"
                f"{prefixed(text, speaker)}\n"
                for position, (start, end, text, speaker) in enumerate(collected, start=1)
            ]
            srt_path = path.with_suffix(".srt")
            srt_path.write_text("\n".join(blocks), encoding="utf-8")
            written.append(srt_path)

        return written


PALETTES = {
    "light": {
        "field": "#ffffff",
        "ink": "#1b1b1b",
        "muted": "#616161",
        "line": "#e0e0e0",
        "select": "#0f6cbd",
        "select_ink": "#ffffff",
        "accent_ink": "#0f6cbd",
        "track": "#d8d8d8",
    },
    "dark": {
        "field": "#2b2b2b",
        "ink": "#f2f2f2",
        "muted": "#a6a6a6",
        "line": "#3d3d3d",
        "select": "#4cc2ff",
        "select_ink": "#1b1b1b",
        "accent_ink": "#6fc9ff",
        "track": "#3d3d3d",
    },
}


class ProgressBar(tk.Canvas):
    """Barre de progression dessinee a la main.

    La barre ttk rend une gouttiere noire selon le theme installe ; celle-ci a
    exactement le meme rendu partout, en clair comme en sombre.
    """

    THICKNESS = 8

    def __init__(self, parent):
        super().__init__(parent, height=self.THICKNESS, highlightthickness=0, borderwidth=0)
        self.value = 0.0
        self.colors = PALETTES["light"]
        self.bind("<Configure>", lambda _event: self.redraw())

    def set_palette(self, colors, background):
        self.colors = colors
        self.configure(background=background)
        self.redraw()

    def set_value(self, value):
        self.value = max(0.0, min(100.0, float(value)))
        self.redraw()

    def capsule(self, right, color):
        height = self.THICKNESS
        radius = height / 2
        right = max(right, height)
        self.create_oval(0, 0, height, height, fill=color, outline=color)
        self.create_oval(right - height, 0, right, height, fill=color, outline=color)
        self.create_rectangle(radius, 0, right - radius, height, fill=color, outline=color)

    def redraw(self):
        self.delete("all")
        width = self.winfo_width()
        if width <= 1:
            return
        self.capsule(width, self.colors["track"])
        if self.value > 0:
            self.capsule(width * self.value / 100, self.colors["select"])


def pick_font(size: int, weight: str = "normal"):
    """Choisit la plus belle police disponible sur la machine."""
    available = set(tkfont.families())
    for family in ("Segoe UI Variable Text", "Segoe UI", "Inter", "Ubuntu", "DejaVu Sans"):
        if family in available:
            return (family, size, weight)
    return ("TkDefaultFont", size, weight)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Transcription audio")
        self.geometry("900x840")
        self.minsize(820, 720)

        self.files: list[str] = []
        self.events: queue.Queue = queue.Queue()
        self.worker: Transcriber | None = None
        self.theme = "light"

        self.fonts = {
            "title": pick_font(20, "bold"),
            "subtitle": pick_font(10),
            "section": pick_font(10, "bold"),
            "body": pick_font(10),
            "small": pick_font(9),
            "mono": pick_font(10),
            "status": pick_font(10),
        }

        self.apply_theme(self.theme)
        self.build_ui()
        self.paint()
        self.after(100, self.drain_events)

    # ── Apparence ────────────────────────────────────────────────────────────
    def apply_theme(self, mode: str):
        self.theme = mode
        try:
            import sv_ttk

            sv_ttk.set_theme(mode)
        except Exception:  # noqa: BLE001 - theme moderne absent, on garde un rendu correct
            style = ttk.Style(self)
            if "vista" in style.theme_names():
                style.theme_use("vista")
            elif "clam" in style.theme_names():
                style.theme_use("clam")

    def paint(self):
        """Applique la palette aux widgets qui ne suivent pas le theme ttk."""
        colors = PALETTES[self.theme]

        for label in getattr(self, "muted_labels", []):
            label.configure(foreground=colors["muted"], font=self.fonts["small"])

        self.listbox_holder.configure(
            background=colors["field"],
            highlightbackground=colors["line"],
            highlightcolor=colors["line"],
        )
        self.files_list.configure(
            background=colors["field"],
            foreground=colors["ink"],
            selectbackground=colors["select"],
            selectforeground=colors["select_ink"],
            highlightbackground=colors["line"],
            highlightcolor=colors["line"],
            font=self.fonts["body"],
        )
        self.preview.configure(
            background=colors["field"],
            foreground=colors["ink"],
            insertbackground=colors["ink"],
            selectbackground=colors["select"],
            selectforeground=colors["select_ink"],
            highlightbackground=colors["line"],
            highlightcolor=colors["line"],
            font=self.fonts["mono"],
        )
        self.preview.tag_configure("speaker", foreground=colors["accent_ink"], font=self.fonts["section"])
        self.status.configure(foreground=colors["muted"])
        self.empty_hint.configure(foreground=colors["muted"])
        self.progress.set_palette(colors, ttk.Style(self).lookup("TFrame", "background") or colors["field"])

    def toggle_theme(self):
        self.apply_theme("dark" if self.theme == "light" else "light")
        self.theme_button.configure(text="Mode sombre" if self.theme == "light" else "Mode clair")
        self.paint()

    # ── Construction ─────────────────────────────────────────────────────────
    def build_ui(self):
        self.muted_labels: list[ttk.Label] = []

        root = ttk.Frame(self, padding=(24, 20, 24, 20))
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)

        self.build_header(root)
        self.build_files_card(root)
        self.build_options_card(root)
        self.build_action_bar(root)
        self.build_preview_card(root)

    def muted(self, parent, text, **grid):
        label = ttk.Label(parent, text=text)
        self.muted_labels.append(label)
        if grid:
            label.grid(**grid)
        return label

    def build_header(self, root):
        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        header.columnconfigure(0, weight=1)

        titles = ttk.Frame(header)
        titles.grid(row=0, column=0, sticky="w")
        ttk.Label(titles, text="Transcription audio", font=self.fonts["title"]).pack(anchor="w")
        self.muted(titles, "Mot a mot, en local sur votre ordinateur. Aucune limite de duree.").pack(
            anchor="w", pady=(2, 0)
        )

        self.theme_button = ttk.Button(header, text="Mode sombre", width=13, command=self.toggle_theme)
        self.theme_button.grid(row=0, column=1, sticky="e")

    def card(self, root, row, title, weight=0):
        holder = ttk.Frame(root)
        holder.grid(row=row, column=0, sticky="nsew", pady=(0, 14))
        holder.columnconfigure(0, weight=1)
        if weight:
            holder.rowconfigure(1, weight=1)

        ttk.Label(holder, text=title, font=self.fonts["section"]).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        body = ttk.Frame(holder, style="Card.TFrame", padding=16)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        return body

    def build_files_card(self, root):
        body = self.card(root, 1, "Fichiers a transcrire")
        body.columnconfigure(0, weight=1)

        listbox_holder = tk.Frame(body, highlightthickness=1, bd=0)
        listbox_holder.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.files_list = tk.Listbox(
            listbox_holder, height=3, activestyle="none", borderwidth=0, highlightthickness=0
        )
        self.files_list.pack(fill="both", expand=True, padx=10, pady=8)
        self.listbox_holder = listbox_holder

        self.empty_hint = ttk.Label(body, text="Aucun fichier pour l'instant.")
        self.empty_hint.grid(row=1, column=0, sticky="w", pady=(8, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=0, column=1, sticky="n")
        ttk.Button(buttons, text="Ajouter...", width=14, command=self.add_files).pack(fill="x", pady=(0, 6))
        ttk.Button(buttons, text="Retirer", width=14, command=self.remove_selected).pack(fill="x", pady=(0, 6))
        ttk.Button(buttons, text="Vider", width=14, command=self.clear_files).pack(fill="x")

    def build_options_card(self, root):
        body = self.card(root, 2, "Options")
        body.columnconfigure(1, weight=1)
        body.columnconfigure(3, weight=1)

        ttk.Label(body, text="Langue").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=(0, 12))
        self.language = ttk.Combobox(body, values=list(LANGUAGES), state="readonly")
        self.language.current(0)
        self.language.grid(row=0, column=1, sticky="ew", padx=(0, 24), pady=(0, 12))

        ttk.Label(body, text="Qualite").grid(row=0, column=2, sticky="w", padx=(0, 10), pady=(0, 12))
        self.model = ttk.Combobox(body, values=list(MODELS), state="readonly")
        self.model.current(0)
        self.model.grid(row=0, column=3, sticky="ew", pady=(0, 12))

        self.with_timestamps = tk.BooleanVar(value=False)
        self.with_srt = tk.BooleanVar(value=False)
        self.use_gpu = tk.BooleanVar(value=True)
        self.with_speakers = tk.BooleanVar(value=False)

        extras = ttk.Frame(body)
        extras.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 6))
        ttk.Checkbutton(extras, text="Fichier horodate en plus", variable=self.with_timestamps).pack(
            side="left", padx=(0, 24)
        )
        ttk.Checkbutton(extras, text="Sous-titres .srt", variable=self.with_srt).pack(side="left", padx=(0, 24))
        ttk.Checkbutton(extras, text="Utiliser le GPU NVIDIA si disponible", variable=self.use_gpu).pack(
            side="left"
        )

        ttk.Separator(body, orient="horizontal").grid(row=2, column=0, columnspan=4, sticky="ew", pady=14)

        ttk.Checkbutton(
            body,
            text="Identifier les interlocuteurs",
            variable=self.with_speakers,
            command=self.refresh_speaker_row,
        ).grid(row=3, column=0, columnspan=4, sticky="w")
        self.muted(
            body,
            "Decoupe le texte par personne : « Interlocuteur 1 : ... ». "
            "Ajoute environ 8 min de calcul par heure d'audio.",
            row=4,
            column=0,
            columnspan=4,
            sticky="w",
            padx=(26, 0),
            pady=(2, 10),
        )

        self.speaker_row = ttk.Frame(body)
        self.speaker_row.grid(row=5, column=0, columnspan=4, sticky="ew", padx=(26, 0))
        ttk.Label(self.speaker_row, text="Combien de personnes parlent ?").pack(side="left", padx=(0, 10))
        self.speaker_count = ttk.Combobox(
            self.speaker_row, values=list(SPEAKER_COUNTS), state="readonly", width=18
        )
        self.speaker_count.current(0)
        self.speaker_count.pack(side="left")
        self.muted(
            body,
            "Donner le nombre exact change tout : sans lui, une meme personne est souvent "
            "comptee plusieurs fois.",
            row=6,
            column=0,
            columnspan=4,
            sticky="w",
            padx=(26, 0),
            pady=(6, 0),
        )
        self.refresh_speaker_row()

    def refresh_speaker_row(self):
        state = "normal" if self.with_speakers.get() else "disabled"
        self.speaker_count.configure(state="readonly" if self.with_speakers.get() else "disabled")
        for child in self.speaker_row.winfo_children():
            if isinstance(child, ttk.Label):
                child.configure(state=state)

    def build_action_bar(self, root):
        bar = ttk.Frame(root)
        bar.grid(row=3, column=0, sticky="ew", pady=(0, 14))
        bar.columnconfigure(2, weight=1)

        self.start_button = ttk.Button(bar, text="Transcrire", style="Accent.TButton", command=self.start)
        self.start_button.grid(row=0, column=0, ipadx=14, ipady=2)
        self.cancel_button = ttk.Button(bar, text="Annuler", command=self.cancel, state="disabled")
        self.cancel_button.grid(row=0, column=1, padx=10)

        self.progress = ProgressBar(bar)
        self.progress.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(14, 6))

        self.status = ttk.Label(bar, text="Ajoutez un fichier pour commencer.", font=self.fonts["status"])
        self.status.grid(row=2, column=0, columnspan=3, sticky="w")

    def build_preview_card(self, root):
        body = self.card(root, 4, "Apercu", weight=1)
        body.rowconfigure(0, weight=1)

        self.preview = tk.Text(
            body, wrap="word", height=6, state="disabled", borderwidth=0, highlightthickness=0,
            padx=12, pady=10, spacing1=2, spacing3=4,
        )
        scrollbar = ttk.Scrollbar(body, command=self.preview.yview)
        self.preview.configure(yscrollcommand=scrollbar.set)
        self.preview.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

    def add_files(self):
        chosen = filedialog.askopenfilenames(title="Choisir les enregistrements", filetypes=AUDIO_TYPES)
        for path in chosen:
            if path not in self.files:
                self.files.append(path)
                self.files_list.insert("end", Path(path).name)
        self.refresh_status()

    def remove_selected(self):
        for position in sorted(self.files_list.curselection(), reverse=True):
            self.files_list.delete(position)
            del self.files[position]
        self.refresh_status()

    def clear_files(self):
        self.files.clear()
        self.files_list.delete(0, "end")
        self.refresh_status()

    def refresh_status(self):
        count = len(self.files)
        if count:
            self.empty_hint.grid_remove()
        else:
            self.empty_hint.grid()
        if self.worker and self.worker.is_alive():
            return
        self.status.configure(
            text="Ajoutez un fichier pour commencer."
            if not count
            else f"{count} fichier(s) pret(s). Cliquez sur Transcrire."
        )

    def start(self):
        if not self.files:
            messagebox.showinfo("Transcription", "Ajoutez au moins un fichier audio.")
            return

        options = {
            "language": LANGUAGES[self.language.get()],
            "model": MODELS[self.model.get()],
            "with_timestamps": self.with_timestamps.get(),
            "with_srt": self.with_srt.get(),
            "use_gpu": self.use_gpu.get(),
            "with_speakers": self.with_speakers.get(),
            "speaker_count": SPEAKER_COUNTS[self.speaker_count.get()],
        }

        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.configure(state="disabled")
        self.progress.set_value(0)
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")

        self.worker = Transcriber(list(self.files), options, self.events)
        self.worker.start()

    def cancel(self):
        if self.worker:
            self.worker.cancelled.set()
            self.status.configure(text="Annulation en cours...")

    def append_preview(self, text):
        self.preview.configure(state="normal")
        # Une ligne par segment : tout coller sur une seule ligne obligeait Tk a
        # recalculer la coupure des mots d'un texte de plus en plus long a chaque ajout.
        self.preview.insert("end", text + "\n")
        excess = int(self.preview.index("end-1c").split(".")[0]) - PREVIEW_MAX_LINES
        if excess > 0:
            self.preview.delete("1.0", f"{excess + 1}.0")
        self.preview.see("end")
        self.preview.configure(state="disabled")

    def finish(self, message):
        self.status.configure(text=message)
        self.start_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.worker = None

    def drain_events(self):
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break

            kind = event["kind"]
            if kind == "status":
                self.status.configure(text=event["text"])
            elif kind == "progress":
                self.progress.set_value(event["value"])
            elif kind == "line":
                self.append_preview(event["text"])
            elif kind == "done":
                self.progress.set_value(100)
                names = "\n".join(str(path) for path in event["outputs"])
                self.finish("Transcription terminee.")
                messagebox.showinfo("Transcription terminee", f"Fichiers ecrits :\n\n{names}")
            elif kind == "cancelled":
                self.progress.set_value(0)
                self.finish("Transcription annulee.")
            elif kind == "failed":
                self.progress.set_value(0)
                self.finish("Echec de la transcription.")
                messagebox.showerror("Erreur", event["message"])

        self.after(100, self.drain_events)


def verifier_installation() -> int:
    """Controle que l'executable embarque bien tous ses composants.

    Appele par la chaine de compilation : un executable auquel il manque une
    bibliotheque native ne se plante qu'au moment de transcrire, c'est-a-dire
    trop tard. Le rapport est ecrit dans un fichier car l'application est
    compilee sans console.
    """
    rapport = Path(sys.executable).with_name("verification.txt")
    try:
        import av  # noqa: F401 - lecture des fichiers audio
        import ctranslate2  # noqa: F401 - moteur de transcription
        import faster_whisper  # noqa: F401
        import onnxruntime  # noqa: F401 - detection des voix
        import sherpa_onnx  # noqa: F401
        import sv_ttk  # noqa: F401 - theme de l'interface

        fenetre = tk.Tk()
        fenetre.withdraw()
        fenetre.destroy()
    except Exception:  # noqa: BLE001 - le detail part dans le rapport
        import traceback

        rapport.write_text(traceback.format_exc(), encoding="utf-8")
        return 1

    rapport.write_text("Tous les composants sont presents.\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    if "--verifier" in sys.argv:
        raise SystemExit(verifier_installation())
    App().mainloop()
