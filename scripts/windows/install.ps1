<#
.SYNOPSIS
  Installe Atelier Nexus sous Windows pour l'utilisateur courant (sans droits d'administrateur).

.DESCRIPTION
  Contrat commun : docs/apps/windows.md (SUITE.md §9) et docs/apps/mise-a-jour-bureau.md (§8).

    powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1              # installer / réparer
    powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -SansBureau  # sans raccourci sur le Bureau
    powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -Desinstaller

  1. Vérifie les prérequis (Git, Node.js 22.12+, Python 3.12+, WebView2) et dit comment installer
     ce qui manque (winget), sans rien installer de système.
  2. Première mise à jour dans ce terminal : environnement Python de l'app
     (%LOCALAPPDATA%\Atelier Nexus\venv), npm ci, compilation de l'interface — AVANT de toucher au
     lanceur existant : en cas d'échec, l'installation précédente reste intacte.
  3. Lanceur (%LOCALAPPDATA%\Atelier Nexus\lanceur) : point d'entrée app_entry.pyw, chemin du dépôt
     (repo-path), icône ; raccourcis menu Démarrer (dossier « Atelier ») et Bureau, qui lancent
     pythonw.exe : aucune console.
  4. Enregistrement HKCU\Software\Atelier\Apps\nexus (Lanceur, Nom) : les autres apps de la suite
     ouvrent Nexus par ce lanceur.

  Relancer la commande répare l'installation. Les données et réglages (%APPDATA%\Atelier Nexus :
  .env, nexus.db) ne sont jamais touchés, ni par l'installation ni par -Desinstaller.
  Après un git pull, rouvrir l'app suffit : elle se met à jour toute seule.

.PARAMETER SansBureau
  Ne crée pas de raccourci sur le Bureau.
.PARAMETER Desinstaller
  Retire lanceur, raccourcis, enregistrement, environnement Python et interface compilée ; garde
  les données, les réglages et les journaux.
.PARAMETER Python
  Python 3.12+ à utiliser (python.exe), au lieu de la recherche automatique (py, python).
.PARAMETER DossierMenuDemarrer
  Dossier des programmes du menu Démarrer (tests : dossier temporaire).
.PARAMETER DossierBureau
  Dossier du Bureau (tests : dossier temporaire).
#>
[CmdletBinding()]
param(
  [switch]$SansBureau,
  [switch]$Desinstaller,
  [string]$Python = '',
  [string]$DossierMenuDemarrer = '',
  [string]$DossierBureau = ''
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
# Sorties des programmes (chemins accentués : C:\Users\François\…) lues en UTF-8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

$AppName = 'Atelier Nexus'
$AppKey = 'nexus'
$RegistryKey = "HKCU:\Software\Atelier\Apps\$AppKey"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$LocalAppData = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME 'AppData\Local' }
$AppData = if ($env:APPDATA) { $env:APPDATA } else { Join-Path $HOME 'AppData\Roaming' }
$LocalDir = Join-Path $LocalAppData $AppName
$LauncherDir = Join-Path $LocalDir 'lanceur'
$DataDir = Join-Path $AppData $AppName
$LogDir = Join-Path $LocalDir 'Logs'
if (-not $DossierMenuDemarrer) { $DossierMenuDemarrer = [Environment]::GetFolderPath('Programs') }
if (-not $DossierBureau) { $DossierBureau = [Environment]::GetFolderPath('Desktop') }
$StartMenuDir = Join-Path $DossierMenuDemarrer 'Atelier'
$ShortcutName = "$AppName.lnk"
$Utf8 = New-Object System.Text.UTF8Encoding $false  # sans BOM

function Say([string]$Text) { Write-Host $Text -ForegroundColor Cyan }
# Programme externe : sa sortie d'erreur n'interrompt jamais le script (Windows PowerShell 5.1
# la transforme sinon en erreur) ; seul le code de retour ($LASTEXITCODE) compte.
function Invoke-Native([scriptblock]$Block) {
  $previous = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try { & $Block } finally { $ErrorActionPreference = $previous }
}
function Info([string]$Text) { Write-Host "  $Text" }
function Fail([string]$Text) {
  Write-Host "Erreur : $Text" -ForegroundColor Red
  exit 1
}

# ─── Désinstallation ──────────────────────────────────────────────

if ($Desinstaller) {
  Say "Désinstallation d'$AppName (données et réglages conservés)"
  foreach ($shortcut in @((Join-Path $StartMenuDir $ShortcutName), (Join-Path $DossierBureau $ShortcutName))) {
    if (Test-Path -LiteralPath $shortcut) {
      Remove-Item -LiteralPath $shortcut -Force
      Info "Raccourci retiré : $shortcut"
    }
  }
  if ((Test-Path -LiteralPath $StartMenuDir) -and -not (Get-ChildItem -LiteralPath $StartMenuDir -Force)) {
    Remove-Item -LiteralPath $StartMenuDir -Force  # dossier « Atelier » vide (aucune autre app)
  }
  if (Test-Path $RegistryKey) {
    Remove-Item -Path $RegistryKey -Recurse -Force
    Info "Enregistrement retiré : $RegistryKey"
  }
  # Lanceur, environnement Python, interface compilée, tampon : rien de tout cela n'est une donnée
  foreach ($name in @('lanceur', 'venv', 'venv.precedent', 'interface', 'mise-a-jour', '.a-supprimer')) {
    $path = Join-Path $LocalDir $name
    if (Test-Path -LiteralPath $path) {
      try {
        Remove-Item -LiteralPath $path -Recurse -Force
      } catch {
        Write-Warning "Impossible de retirer $path (Atelier Nexus est-il encore ouvert ?) : $($_.Exception.Message)"
      }
    }
  }
  Say "✓ $AppName est désinstallée."
  Info "Données et réglages conservés : $DataDir"
  Info "Journaux conservés : $LogDir"
  exit 0
}

# ─── Prérequis ────────────────────────────────────────────────────

Say "1/4 · Prérequis"
$missing = New-Object System.Collections.Generic.List[string]

# Git
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) {
  Info "Git : $((Invoke-Native { & $git.Source --version }) -join ' ')"
} else {
  $missing.Add("Git est introuvable : winget install --id Git.Git -e")
}

# Node.js 22.12+ (npm à côté) — mêmes emplacements que la mise à jour (app/desktop_update.py)
function Find-Node {
  $found = Get-Command node -ErrorAction SilentlyContinue
  if ($found) { return $found.Source }
  $dirs = @()
  if ($env:ProgramFiles) { $dirs += (Join-Path $env:ProgramFiles 'nodejs') }
  if ($env:NVM_SYMLINK) { $dirs += $env:NVM_SYMLINK }
  $dirs += (Join-Path $LocalAppData 'Volta\bin')
  $fnm = if ($env:FNM_DIR) { $env:FNM_DIR } else { Join-Path $AppData 'fnm' }
  $dirs += (Join-Path $fnm 'aliases\default')
  $dirs += (Join-Path $LocalAppData 'Programs\nodejs')
  $dirs += (Join-Path $HOME 'scoop\apps\nodejs\current')
  $dirs += (Join-Path $HOME 'scoop\apps\nodejs-lts\current')
  foreach ($dir in $dirs) {
    $candidate = Join-Path $dir 'node.exe'
    if (Test-Path -LiteralPath $candidate) { return $candidate }
  }
  return $null
}
$node = Find-Node
if ($node) {
  $nodeVersion = ((Invoke-Native { & $node --version }) -join '').Trim().TrimStart('v')
  $parts = $nodeVersion.Split('.')
  $major = [int]$parts[0]; $minor = [int]$parts[1]
  if ($major -gt 22 -or ($major -eq 22 -and $minor -ge 12)) {
    Info "Node.js : v$nodeVersion ($node)"
  } else {
    $missing.Add("Node.js v$nodeVersion est trop ancien (22.12+ requis) : winget install --id OpenJS.NodeJS.LTS -e")
  }
  $npmCmd = Join-Path (Split-Path $node) 'npm.cmd'
  if (-not (Test-Path -LiteralPath $npmCmd) -and -not (Get-Command npm -ErrorAction SilentlyContinue)) {
    $missing.Add("npm est introuvable à côté de Node.js : réinstallez Node.js (winget install --id OpenJS.NodeJS.LTS -e)")
  }
} else {
  $missing.Add("Node.js est introuvable : winget install --id OpenJS.NodeJS.LTS -e")
}

# Python 3.12+ (§9.3 : py -3, puis python) : on retient son python.exe et son pythonw.exe
function Get-PythonInfo([string]$Exe, [string[]]$Arguments) {
  try {
    $out = Invoke-Native { & $Exe @Arguments -I -c "import sys; print(sys.version_info[0] * 100 + sys.version_info[1]); print(sys.executable)" 2>$null }
  } catch {
    return $null
  }
  if ($LASTEXITCODE -ne 0 -or -not $out -or @($out).Count -lt 2) { return $null }  # alias du Microsoft Store
  $lines = @($out)
  $exePath = $lines[1].Trim()
  if (-not (Test-Path -LiteralPath $exePath)) { return $null }
  return [pscustomobject]@{ Version = [int]$lines[0].Trim(); Python = $exePath }
}
function Find-Python {
  if ($Python) {
    $info = Get-PythonInfo $Python @()
    if (-not $info) { Fail "Python indiqué inutilisable : $Python" }
    return $info
  }
  $candidates = @()
  if (Get-Command py -ErrorAction SilentlyContinue) {
    # Versions dont les dépendances (pywebview, pythonnet) sont publiées, puis la plus récente
    $candidates += , @('py', @('-3.13'))
    $candidates += , @('py', @('-3.12'))
    $candidates += , @('py', @('-3'))
  }
  if (Get-Command python -ErrorAction SilentlyContinue) { $candidates += , @('python', @()) }
  foreach ($candidate in $candidates) {
    $info = Get-PythonInfo $candidate[0] $candidate[1]
    if ($info -and $info.Version -ge 312) { return $info }
  }
  return $null
}
$py = Find-Python
$pythonw = $null
if ($py) {
  $pythonw = Join-Path (Split-Path $py.Python) 'pythonw.exe'
  if (Test-Path -LiteralPath $pythonw) {
    Info ("Python : {0}.{1} ({2})" -f [math]::Floor($py.Version / 100), ($py.Version % 100), $py.Python)
  } else {
    $missing.Add("pythonw.exe est absent à côté de $($py.Python) : installez Python depuis python.org ou winget install --id Python.Python.3.13 -e")
  }
} else {
  $missing.Add("Python 3.12 ou plus récent est introuvable : winget install --id Python.Python.3.13 -e")
}

# WebView2 (fenêtre de l'app) : présent sur Windows 11 et sur Windows 10 à jour ; sinon, navigateur
$clientId = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
$webview2 = $false
foreach ($key in @(
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$clientId",
    "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$clientId",
    "HKCU:\Software\Microsoft\EdgeUpdate\Clients\$clientId")) {
  $pv = (Get-ItemProperty -Path $key -Name pv -ErrorAction SilentlyContinue)
  if ($pv -and $pv.pv -and $pv.pv -ne '0.0.0.0') { $webview2 = $true; Info "WebView2 : $($pv.pv)"; break }
}
if (-not $webview2) {
  Write-Warning "WebView2 est absent : Atelier Nexus s'ouvrira dans le navigateur. Pour une fenêtre native : winget install --id Microsoft.EdgeWebView2Runtime -e"
}

if ($missing.Count -gt 0) {
  Write-Host ''
  Write-Host 'Prérequis manquants (à installer, puis relancez cette commande) :' -ForegroundColor Yellow
  foreach ($item in $missing) { Write-Host "  • $item" -ForegroundColor Yellow }
  exit 1
}

# ─── Première mise à jour (avant de toucher au lanceur) ───────────

Say "2/4 · Première mise à jour (environnement Python, npm ci, compilation de l'interface)"
$env:NEXUS_REPO = $Repo
if ($node) { $env:PATH = (Split-Path $node) + ';' + $env:PATH }  # npm trouvé comme par l'app
Invoke-Native { & $py.Python -I (Join-Path $Repo 'backend\app\desktop_launcher.py') --preparer }
if ($LASTEXITCODE -ne 0) {
  Fail "la mise à jour a échoué (détails : $(Join-Path $LogDir 'mise-a-jour.log')). L'installation précédente est intacte."
}

# ─── Lanceur et raccourcis ────────────────────────────────────────

Say "3/4 · Lanceur et raccourcis"
New-Item -ItemType Directory -Force -Path $LauncherDir | Out-Null
Copy-Item -LiteralPath (Join-Path $Repo 'scripts\windows\app_entry.pyw') -Destination (Join-Path $LauncherDir 'atelier-nexus.pyw') -Force
Copy-Item -LiteralPath (Join-Path $Repo 'scripts\windows\AtelierNexus.ico') -Destination (Join-Path $LauncherDir 'AtelierNexus.ico') -Force
[System.IO.File]::WriteAllText((Join-Path $LauncherDir 'repo-path'), $Repo + "`n", $Utf8)

$shell = New-Object -ComObject WScript.Shell
function New-AppShortcut([string]$Path) {
  $parent = Split-Path $Path
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
  if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Force }
  $link = $shell.CreateShortcut($Path)
  $link.TargetPath = $pythonw
  $link.Arguments = '-I "' + (Join-Path $LauncherDir 'atelier-nexus.pyw') + '"'
  $link.WorkingDirectory = $LauncherDir
  $link.IconLocation = (Join-Path $LauncherDir 'AtelierNexus.ico') + ',0'
  $link.Description = 'Atelier Nexus — agents IA de la suite Atelier'
  $link.WindowStyle = 1
  $link.Save()
  Info "Raccourci : $Path"
}
$launcher = Join-Path $LauncherDir $ShortcutName
New-AppShortcut $launcher
New-AppShortcut (Join-Path $StartMenuDir $ShortcutName)
$desktopShortcut = Join-Path $DossierBureau $ShortcutName
if ($SansBureau) {
  if (Test-Path -LiteralPath $desktopShortcut) { Remove-Item -LiteralPath $desktopShortcut -Force }
} else {
  New-AppShortcut $desktopShortcut
}

# ─── Enregistrement (§9.4) ────────────────────────────────────────

Say "4/4 · Enregistrement ($RegistryKey)"
New-Item -Path $RegistryKey -Force | Out-Null
New-ItemProperty -Path $RegistryKey -Name 'Lanceur' -Value $launcher -PropertyType String -Force | Out-Null
New-ItemProperty -Path $RegistryKey -Name 'Nom' -Value $AppName -PropertyType String -Force | Out-Null

Write-Host ''
Say "✓ $AppName est installée."
Info "• Ouvrez « $AppName » depuis le menu Démarrer (dossier Atelier)$(if (-not $SansBureau) { ' ou le Bureau' })."
Info "• Elle lance le code de ce dépôt : $Repo"
Info "• Après un git pull, rouvrez simplement l'app : elle se met à jour toute seule (écran « Mise à jour… »)."
Info "• Réglages (clé Claude, adresses des apps) : menu Réglages de l'app, ou $(Join-Path $DataDir '.env')"
Info "• Journaux : $LogDir (atelier-nexus.log, mise-a-jour.log)"
Info "• Si le dépôt change de place, relancez cette commande depuis son nouvel emplacement."
exit 0
