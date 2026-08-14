"""Transcription audio mot a mot, en local, sans limite de duree."""

import os
import queue
import tarfile
import threading
import tkinter as tk
import urllib.request
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

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
# Seuil de regroupement des voix. Mesure sur enregistrement reel : 0.5 retrouve le bon
# nombre d'interlocuteurs la ou le comptage force (num_clusters) se trompe.
DIARIZATION_THRESHOLD = 0.5
SAMPLE_RATE = 16_000

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


def build_diarizer(segmentation: Path, embedding: Path):
    try:
        import sherpa_onnx
    except ImportError as error:
        raise RuntimeError(
            "Le composant d'identification des interlocuteurs n'est pas installe.\n"
            "Relancez Installer.bat pour l'ajouter."
        ) from error

    threads = max(1, (os.cpu_count() or 4) - 1)
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(segmentation)),
            num_threads=threads,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(embedding), num_threads=threads),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=DIARIZATION_THRESHOLD),
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

    def run(self):
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
        diarizer = build_diarizer(segmentation, embedding)

        def report(processed, chunks):
            if self.cancelled.is_set():
                return 1
            if chunks:
                self.emit("progress", value=processed / chunks * 100)
                self.emit(
                    "status",
                    text=f"[{index}/{total}] Identification des interlocuteurs : {processed * 100 // chunks} %",
                )
            return 0

        result = diarizer.process(audio, callback=report)
        if self.cancelled.is_set():
            return []

        turns = [(item.start, item.end, item.speaker) for item in result.sort_by_start_time()]
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

        for segment in segments:
            if self.cancelled.is_set():
                return []
            text = segment.text.strip()
            if text:
                collected.append((segment.start, segment.end, text))
            if duration:
                self.emit("progress", value=min(100, segment.end / duration * 100))
            self.emit(
                "status",
                text=f"[{index}/{total}] {path.name} — {format_clock(segment.end)} / {format_clock(duration)}",
            )
            self.emit("line", text=text)

        return self.write_outputs(path, assign_speakers(collected, turns))

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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Transcription audio")
        self.geometry("760x600")
        self.minsize(640, 520)

        self.files: list[str] = []
        self.events: queue.Queue = queue.Queue()
        self.worker: Transcriber | None = None

        self.build_ui()
        self.after(100, self.drain_events)

    def build_ui(self):
        padding = {"padx": 14, "pady": 6}

        header = ttk.Frame(self)
        header.pack(fill="x", **padding)
        ttk.Label(header, text="Transcription audio", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            header,
            text="Transcription mot a mot, en local sur votre ordinateur. Aucune limite de duree.",
            foreground="#555555",
        ).pack(anchor="w")

        files_frame = ttk.LabelFrame(self, text="Fichiers a transcrire")
        files_frame.pack(fill="both", expand=False, **padding)

        self.files_list = tk.Listbox(files_frame, height=5, activestyle="none")
        self.files_list.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        buttons = ttk.Frame(files_frame)
        buttons.pack(side="right", fill="y", padx=8, pady=8)
        ttk.Button(buttons, text="Ajouter...", command=self.add_files).pack(fill="x", pady=2)
        ttk.Button(buttons, text="Retirer", command=self.remove_selected).pack(fill="x", pady=2)
        ttk.Button(buttons, text="Vider", command=self.clear_files).pack(fill="x", pady=2)

        options = ttk.LabelFrame(self, text="Options")
        options.pack(fill="x", **padding)
        options.columnconfigure(1, weight=1)
        options.columnconfigure(3, weight=1)

        ttk.Label(options, text="Langue").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.language = ttk.Combobox(options, values=list(LANGUAGES), state="readonly")
        self.language.current(0)
        self.language.grid(row=0, column=1, sticky="ew", padx=8, pady=6)

        ttk.Label(options, text="Qualite").grid(row=0, column=2, sticky="w", padx=8, pady=6)
        self.model = ttk.Combobox(options, values=list(MODELS), state="readonly")
        self.model.current(0)
        self.model.grid(row=0, column=3, sticky="ew", padx=8, pady=6)

        self.with_timestamps = tk.BooleanVar(value=False)
        self.with_srt = tk.BooleanVar(value=False)
        self.use_gpu = tk.BooleanVar(value=True)
        self.with_speakers = tk.BooleanVar(value=False)

        ttk.Checkbutton(options, text="Fichier horodate en plus", variable=self.with_timestamps).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=8, pady=2
        )
        ttk.Checkbutton(options, text="Sous-titres .srt", variable=self.with_srt).grid(
            row=1, column=2, columnspan=2, sticky="w", padx=8, pady=2
        )
        ttk.Checkbutton(
            options,
            text="Identifier les interlocuteurs (Interlocuteur 1, Interlocuteur 2, ...)",
            variable=self.with_speakers,
        ).grid(row=2, column=0, columnspan=4, sticky="w", padx=8, pady=2)
        ttk.Label(
            options,
            text="Ajoute environ 8 min de calcul par heure d'audio. Telechargement de 37 Mo au premier usage.",
            foreground="#555555",
        ).grid(row=3, column=0, columnspan=4, sticky="w", padx=28, pady=(0, 2))
        ttk.Checkbutton(options, text="Utiliser le GPU NVIDIA s'il est disponible", variable=self.use_gpu).grid(
            row=4, column=0, columnspan=4, sticky="w", padx=8, pady=(2, 8)
        )

        actions = ttk.Frame(self)
        actions.pack(fill="x", **padding)
        self.start_button = ttk.Button(actions, text="Transcrire", command=self.start)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="Annuler", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=8)

        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.progress.pack(fill="x", **padding)

        self.status = ttk.Label(self, text="Ajoutez un fichier pour commencer.", foreground="#555555")
        self.status.pack(fill="x", padx=14)

        preview_frame = ttk.LabelFrame(self, text="Apercu")
        preview_frame.pack(fill="both", expand=True, **padding)
        self.preview = tk.Text(preview_frame, wrap="word", height=10, state="disabled")
        scrollbar = ttk.Scrollbar(preview_frame, command=self.preview.yview)
        self.preview.configure(yscrollcommand=scrollbar.set)
        self.preview.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        scrollbar.pack(side="right", fill="y", padx=(0, 8), pady=8)

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
        if self.worker and self.worker.is_alive():
            return
        count = len(self.files)
        self.status.configure(
            text="Ajoutez un fichier pour commencer." if not count else f"{count} fichier(s) pret(s)."
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
        }

        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.configure(state="disabled")
        self.progress.configure(value=0)
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
        self.preview.insert("end", text + " ")
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
                self.progress.configure(value=event["value"])
            elif kind == "line":
                self.append_preview(event["text"])
            elif kind == "done":
                self.progress.configure(value=100)
                names = "\n".join(str(path) for path in event["outputs"])
                self.finish("Transcription terminee.")
                messagebox.showinfo("Transcription terminee", f"Fichiers ecrits :\n\n{names}")
            elif kind == "cancelled":
                self.progress.configure(value=0)
                self.finish("Transcription annulee.")
            elif kind == "failed":
                self.progress.configure(value=0)
                self.finish("Echec de la transcription.")
                messagebox.showerror("Erreur", event["message"])

        self.after(100, self.drain_events)


if __name__ == "__main__":
    App().mainloop()
