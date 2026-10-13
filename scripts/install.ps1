# Install Roundtable for the current user (Windows PowerShell). No admin rights needed.
# Usage:  powershell -ExecutionPolicy Bypass -File install.ps1   (set $env:REPO_URL to use your fork)
$ErrorActionPreference = "Stop"
$RepoUrl = if ($env:REPO_URL) { $env:REPO_URL } else { "https://github.com/OWNER/roundtable" }
$Spec = "git+$RepoUrl"

function Fail($msg) { Write-Host "roundtable install: $msg" -ForegroundColor Red; exit 1 }

$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) { $Python = "py"; $PyArgs = @("-3") } else {
  $p = Get-Command python -ErrorAction SilentlyContinue
  if (-not $p) { Fail "Python 3.10+ is required. Install it from https://www.python.org/downloads/ (tick 'Add to PATH') and run this again." }
  $Python = "python"; $PyArgs = @()
}
& $Python @PyArgs -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) { Fail "Python 3.10+ is required." }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail "git is required. Install it from https://git-scm.com/downloads and run this again." }

if (Get-Command uv -ErrorAction SilentlyContinue) {
  Write-Host "installing with uv: $Spec"; uv tool install --force $Spec
} elseif (Get-Command pipx -ErrorAction SilentlyContinue) {
  Write-Host "installing with pipx: $Spec"; pipx install --force $Spec
} else {
  Write-Host "neither uv nor pipx found; installing pipx for your user first"
  & $Python @PyArgs -m pip install --user pipx
  & $Python @PyArgs -m pipx ensurepath
  & $Python @PyArgs -m pipx install --force $Spec
}
if ($LASTEXITCODE -ne 0) { Fail "installation failed; see the messages above." }
Write-Host ""
Write-Host "Roundtable installed. If 'rt' is not found, open a new terminal."
Write-Host "Next, in your project folder:  rt init   then   rt seat add <name> --model <model> --app claude-code|codex-cli|claude-app|codex-app"
