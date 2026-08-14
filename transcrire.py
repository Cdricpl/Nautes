"""Transcription audio mot a mot, en local, sans limite de duree."""

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

AUDIO_TYPES = [
    ("Fichiers audio et video", "*.mp3 *.m4a *.wav *.flac *.ogg *.opus *.aac *.wma *.mp4 *.mov *.avi *.mkv"),
    ("Tous les fichiers", "*.*"),
]

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

    for start, _end, text in segments:
        if previous_end is not None and start - previous_end > gap and current:
            paragraphs.append(current)
            current = []
        current.append(text)
        previous_end = _end

    if current:
        paragraphs.append(current)

    return "\n\n".join(" ".join(part).strip() for part in paragraphs)


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

    def transcribe_one(self, model, path: Path, index: int):
        total = len(self.files)
        self.emit("status", text=f"[{index}/{total}] Analyse de {path.name}...")
        self.emit("progress", value=0)

        segments, info = model.transcribe(
            str(path),
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

        return self.write_outputs(path, collected)

    def write_outputs(self, path: Path, collected):
        written = []

        text_path = path.with_suffix(".txt")
        text_path.write_text(build_paragraphs(collected) + "\n", encoding="utf-8")
        written.append(text_path)

        if self.options["with_timestamps"]:
            stamped = "\n".join(f"[{format_clock(start)}] {text}" for start, _end, text in collected)
            stamped_path = path.with_name(f"{path.stem}_horodate.txt")
            stamped_path.write_text(stamped + "\n", encoding="utf-8")
            written.append(stamped_path)

        if self.options["with_srt"]:
            blocks = [
                f"{position}\n{format_srt_time(start)} --> {format_srt_time(end)}\n{text}\n"
                for position, (start, end, text) in enumerate(collected, start=1)
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

        ttk.Checkbutton(options, text="Fichier horodate en plus", variable=self.with_timestamps).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=8, pady=2
        )
        ttk.Checkbutton(options, text="Sous-titres .srt", variable=self.with_srt).grid(
            row=1, column=2, columnspan=2, sticky="w", padx=8, pady=2
        )
        ttk.Checkbutton(options, text="Utiliser le GPU NVIDIA s'il est disponible", variable=self.use_gpu).grid(
            row=2, column=0, columnspan=4, sticky="w", padx=8, pady=(2, 8)
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
