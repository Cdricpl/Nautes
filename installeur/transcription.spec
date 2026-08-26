# Recette de compilation PyInstaller — executee sur une machine Windows.
# Les bibliotheques utilisees embarquent des fichiers natifs (DLL, modeles ONNX,
# themes Tcl) que PyInstaller ne trouve pas seul : chacune est donc collectee
# explicitement, sinon l'executable se construit mais echoue a l'usage.

from PyInstaller.utils.hooks import collect_all

PAQUETS = [
    "faster_whisper",     # transcription
    "ctranslate2",        # moteur de calcul
    "av",                 # lecture des fichiers audio et video
    "tokenizers",
    "huggingface_hub",    # telechargement des modeles au premier usage
    "onnxruntime",        # execution des modeles de voix
    "sherpa_onnx",        # identification des interlocuteurs
    "sherpa_onnx_core",   # bibliotheques natives de sherpa-onnx
    "sv_ttk",             # theme de l'interface (fichiers Tcl)
]

datas, binaries, hiddenimports = [], [], []
for paquet in PAQUETS:
    try:
        d, b, h = collect_all(paquet)
    except Exception as erreur:  # noqa: BLE001 - paquet absorbe par un autre
        print(f"[recette] {paquet} ignore : {erreur}")
        continue
    datas += d
    binaries += b
    hiddenimports += h

analyse = Analysis(
    ["../transcrire.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "pytest", "IPython", "pandas", "scipy"],
    noarchive=False,
)

pyz = PYZ(analyse.pure)

executable = EXE(
    pyz,
    analyse.scripts,
    [],
    exclude_binaries=True,
    name="TranscriptionAudio",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # pas de fenetre noire derriere l'application
    icon="../icone.ico",
)

COLLECT(
    executable,
    analyse.binaries,
    analyse.datas,
    strip=False,
    upx=False,
    name="TranscriptionAudio",
)
