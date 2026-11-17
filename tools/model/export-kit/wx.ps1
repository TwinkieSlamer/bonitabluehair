# Sends JavaScript to the helper (bbh-auto.js) inside a running copy of wow.export and prints its answer as JSON.
#   & wx.ps1 -File step-look.js                    (a step script from this folder)
#   & wx.ps1 -Code 'return document.title'         (a one-liner)
# -Dir is the folder the app was started with in BBH_IO; it defaults to that same environment variable here.
param([string]$Code, [string]$File, [int]$Timeout = 90, [string]$Dir = $env:BBH_IO)
if (-not $Dir) { "No folder: pass -Dir or set BBH_IO"; exit 1 }
if ($File) { $Code = [IO.File]::ReadAllText($File) }
$id = [guid]::NewGuid().ToString("N").Substring(0, 8)
[IO.File]::WriteAllText((Join-Path $Dir "cmd.js"), "// id:$id`n" + $Code)
$deadline = (Get-Date).AddSeconds($Timeout)
while ((Get-Date) -lt $deadline) {
  $o = Join-Path $Dir "out.json"
  if (Test-Path $o) {
    try { $j = Get-Content $o -Raw | ConvertFrom-Json; if ($j.cmd -eq $id) { Get-Content $o -Raw; return } } catch {}
  }
  Start-Sleep -Milliseconds 300
}
"TIMEOUT waiting for $id"
