; Recette de l'installateur Windows (Inno Setup).
; Installation par utilisateur : aucune demande de mot de passe administrateur.

#define MonNom "Transcription audio"
#define MonExe "TranscriptionAudio.exe"

[Setup]
AppName={#MonNom}
AppVersion=1.0.0
AppPublisher=Transcription audio
DefaultDirName={autopf}\{#MonNom}
DefaultGroupName={#MonNom}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=TranscriptionAudio-Installateur
SetupIconFile=..\icone.ico
UninstallDisplayIcon={app}\{#MonExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "francais"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "raccourcibureau"; Description: "Creer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"

[Files]
Source: "..\dist\TranscriptionAudio\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MonNom}"; Filename: "{app}\{#MonExe}"
Name: "{group}\Desinstaller {#MonNom}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MonNom}"; Filename: "{app}\{#MonExe}"; Tasks: raccourcibureau

[Run]
Filename: "{app}\{#MonExe}"; Description: "Lancer {#MonNom}"; Flags: nowait postinstall skipifsilent
