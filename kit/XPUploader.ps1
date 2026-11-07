# XP Uploader for bonitabluehair.com
#
# What it does, in order:
#   1. Finds XPReport.lua, the file the XPReport addon saves inside your World of Warcraft folder.
#   2. Every 10 seconds, checks whether WoW has rewritten that file (it does when you log out or /reload).
#   3. When it has, reads Bonita's level, XP, and level-up times from it. That is all it reads.
#   4. Sends those numbers to the live-XP repo on GitHub as live.json. The website picks them up from there.
#
# It never reads anything else on your PC, never touches the game itself, and only talks to api.github.com.
# The GitHub key you paste the first time is saved encrypted for your Windows user only
# (%APPDATA%\XPUploader\token.txt). Delete that folder to forget it.
#
# Options:
#   -SavedVariables <path>  use this XPReport.lua instead of searching for it
#   -DryRun                 show what would be uploaded, upload nothing
#   -Once                   check one time and exit instead of watching
param(
  [string]$SavedVariables,
  [switch]$DryRun,
  [switch]$Once
)

$ErrorActionPreference = "Stop"
$Repo = "TwinkieSlamer/bonitabluehair-live"
$RemotePath = "live.json"
$Character = "Bonita"
$ConfigDir = Join-Path $env:APPDATA "XPUploader"
$TokenFile = Join-Path $ConfigDir "token.txt"
$StateFile = Join-Path $ConfigDir "state.json"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Say($msg, $color = "Gray") { Write-Host ("[{0}] {1}" -f (Get-Date -Format "h:mm tt"), $msg) -ForegroundColor $color }

# ---------- 1. Find the SavedVariables file ----------
function Find-SavedVariables {
  $roots = New-Object System.Collections.Generic.List[string]
  foreach ($key in @("HKLM:\SOFTWARE\WOW6432Node\Blizzard Entertainment\World of Warcraft",
                     "HKLM:\SOFTWARE\Blizzard Entertainment\World of Warcraft")) {
    try {
      $p = (Get-ItemProperty -Path $key -ErrorAction Stop).InstallPath
      if ($p) { $roots.Add($p); $roots.Add((Split-Path $p -Parent)) }
    } catch { }
  }
  foreach ($drive in (Get-PSDrive -PSProvider FileSystem | ForEach-Object Root)) {
    foreach ($sub in @("Program Files (x86)\World of Warcraft", "Program Files\World of Warcraft", "World of Warcraft", "Games\World of Warcraft", "Battle.net\World of Warcraft")) {
      $roots.Add((Join-Path $drive $sub))
    }
  }
  $found = foreach ($root in ($roots | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $root)) { continue }
    Get-ChildItem -Path (Join-Path $root "*\WTF\Account\*\SavedVariables\XPReport.lua") -ErrorAction SilentlyContinue
    Get-ChildItem -Path (Join-Path $root "WTF\Account\*\SavedVariables\XPReport.lua") -ErrorAction SilentlyContinue
  }
  $found | Sort-Object LastWriteTime -Descending | Select-Object -First 1
}

# ---------- 2. Read the Lua table WoW wrote ----------
# A small reader for the table format WoW uses in SavedVariables files.
function Read-LuaTable([string]$text, [string]$varName) {
  $pattern = '--[^\r\n]*|"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|[A-Za-z_][A-Za-z0-9_]*|[{}\[\]=,;]'
  $script:tok = @([regex]::Matches($text, $pattern) | ForEach-Object { $_.Value } | Where-Object { -not $_.StartsWith("--") })
  $script:pos = 0
  while ($script:pos -lt $script:tok.Count) {
    if ($script:tok[$script:pos] -eq $varName -and $script:tok[$script:pos + 1] -eq "=") {
      $script:pos += 2
      return (Read-LuaValue)
    }
    $script:pos++
  }
  return $null
}
function Read-LuaValue {
  $t = $script:tok[$script:pos]; $script:pos++
  if ($t -eq "{") { return (Read-LuaTableBody) }
  if ($t.StartsWith('"')) { return ($t.Substring(1, $t.Length - 2) -replace '\\"', '"' -replace '\\\\', '\') }
  if ($t -eq "true") { return $true }
  if ($t -eq "false") { return $false }
  if ($t -eq "nil") { return $null }
  return [double]::Parse($t, [Globalization.CultureInfo]::InvariantCulture)
}
function Read-LuaTableBody {
  $map = @{}; $list = New-Object System.Collections.ArrayList
  while ($script:pos -lt $script:tok.Count) {
    $t = $script:tok[$script:pos]
    if ($t -eq "}") { $script:pos++; break }
    if ($t -eq "," -or $t -eq ";") { $script:pos++; continue }
    if ($t -eq "[") {
      $script:pos++; $k = Read-LuaValue; $script:pos++  # skip ]
      $script:pos++                                       # skip =
      $map["$k"] = Read-LuaValue
    } elseif ($script:tok[$script:pos + 1] -eq "=" -and $t -match '^[A-Za-z_]') {
      $script:pos += 2; $map[$t] = Read-LuaValue
    } else {
      [void]$list.Add((Read-LuaValue))
    }
  }
  if ($map.Count -eq 0 -and $list.Count -gt 0) { return ,$list.ToArray() }
  return $map
}

function Get-Reading($path) {
  $db = Read-LuaTable ([IO.File]::ReadAllText($path)) "XPReportDB"
  if (-not $db -or $db.Count -eq 0) { return $null }
  $name = @($db.Keys | Where-Object { $_ -like "*$Character*" })[0]
  if (-not $name) { throw "No character named like '$Character' in XPReport.lua yet. Found: $($db.Keys -join ', ')" }
  $e = $db[$name]
  $dings = @()
  foreach ($d in @($e["dings"])) { if ($d) { $dings += [ordered]@{ level = [int]$d["level"]; time = [long]$d["time"] } } }
  return [ordered]@{
    source = "XPReport addon"
    character = $name
    level = [int]$e["level"]
    xp = [long]$e["xp"]
    xpMax = [long]$e["xpMax"]
    time = [long]$e["time"]
    dings = $dings
    uploadedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
  }
}

# ---------- 3. Send it to GitHub ----------
function Get-Token {
  if (Test-Path $TokenFile) {
    $secure = Get-Content $TokenFile | ConvertTo-SecureString
    return [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
  }
  Write-Host ""
  Write-Host "First run: paste the GitHub key you were sent (it starts with github_pat_), then press Enter." -ForegroundColor Cyan
  $secure = Read-Host "GitHub key" -AsSecureString
  New-Item -ItemType Directory -Force $ConfigDir | Out-Null
  $secure | ConvertFrom-SecureString | Set-Content $TokenFile
  return [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
}

function Send-Reading($reading, $token) {
  $headers = @{ Authorization = "Bearer $token"; Accept = "application/vnd.github+json"; "X-GitHub-Api-Version" = "2022-11-28"; "User-Agent" = "XPUploader" }
  $url = "https://api.github.com/repos/$Repo/contents/$RemotePath"
  $sha = $null
  try { $sha = (Invoke-RestMethod -Uri "${url}?ref=main" -Headers $headers).sha } catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -ne 404) { throw }
  }
  $json = $reading | ConvertTo-Json -Depth 5
  $pct = if ($reading.xpMax -gt 0) { [math]::Floor($reading.xp * 100 / $reading.xpMax) } else { 0 }
  $body = @{ message = "Live XP: level $($reading.level), $pct%"; branch = "main"
             content = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json)) }
  if ($sha) { $body.sha = $sha }
  Invoke-RestMethod -Method Put -Uri $url -Headers $headers -ContentType "application/json" -Body ($body | ConvertTo-Json) | Out-Null
}

# ---------- Main ----------
Write-Host "XP Uploader for bonitabluehair.com" -ForegroundColor Cyan
if (-not $SavedVariables) {
  $file = Find-SavedVariables
  if (-not $file) {
    Say "Couldn't find XPReport.lua. Log in once with the XPReport addon enabled, log out, then run this again." "Yellow"
    Say "Or run it with -SavedVariables `"<path to XPReport.lua>`"." "Yellow"
    if (-not $Once) { Read-Host "Press Enter to close" }
    exit 1
  }
  $SavedVariables = $file.FullName
}
Say "Watching $SavedVariables"
$token = if ($DryRun) { $null } else { Get-Token }
$lastSent = 0
if (Test-Path $StateFile) { try { $lastSent = [long](Get-Content $StateFile | ConvertFrom-Json).time } catch { } }
$lastWrite = [datetime]::MinValue

while ($true) {
  try {
    $w = (Get-Item -LiteralPath $SavedVariables).LastWriteTimeUtc
    if ($w -ne $lastWrite) {
      $lastWrite = $w
      $r = Get-Reading $SavedVariables
      if ($r -and $r.time -gt $lastSent) {
        $pct = if ($r.xpMax -gt 0) { [math]::Floor($r.xp * 100 / $r.xpMax) } else { 0 }
        if ($DryRun) {
          Say "Would upload: level $($r.level), $($r.xp) / $($r.xpMax) XP ($pct%)" "Green"
          ($r | ConvertTo-Json -Depth 5) | Write-Host
        } else {
          Send-Reading $r $token
          $lastSent = $r.time
          New-Item -ItemType Directory -Force $ConfigDir | Out-Null
          @{ time = $lastSent } | ConvertTo-Json | Set-Content $StateFile
          Say "Uploaded: level $($r.level), $pct% into the level" "Green"
        }
      } elseif ($r) { Say "No new XP since the last upload." }
    }
  } catch {
    $msg = $_.Exception.Message
    if ($msg -match "401|403") { $msg = "GitHub refused the key ($msg). Delete $TokenFile and run again with a fresh key." }
    Say "Problem: $msg" "Yellow"
  }
  if ($Once) { break }
  Start-Sleep -Seconds 10
}
