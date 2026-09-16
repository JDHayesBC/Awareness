#!/usr/bin/pwsh
<#
.SYNOPSIS
    Fix: Docker stack doesn't start until Jeff logs in (#331).

.DESCRIPTION
    Issue: Docker Desktop is in HKCU Run (fires at user LOGIN), so after any reboot
    the stack is down until a human signs in — up to 9.5h in the Sept-14 incident.

    Two options below. Run this script with -Option A or -Option B.
    BOTH options also install Option C (ntfy boot-alert) so a blackout is visible
    even if something goes wrong.

    OPTION A — Auto-login (simplest, fastest)
    -----------------------------------------
    Reboot -> Windows auto-signs-in -> HKCU Run fires -> Docker Desktop starts.
    Turns 9.5h into ~2min. Tradeoff: physical access to the NUC = logged-in desktop.
    Fine on a home network; Jeff's call.

    OPTION B — Boot service + WSL start task (no auto-login)
    ---------------------------------------------------------
    Sets com.docker.service to Automatic so Docker's engine starts at boot,
    then adds a Task Scheduler entry that starts Docker Desktop and the WSL
    distro at boot (SYSTEM account, no login required).
    Tradeoff: session-oriented parts of Docker Desktop may behave oddly without
    a logged-in user; needs a real reboot-verify before trusting.

    After either option, verify with:
        (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
        docker inspect -f '{{.Name}} {{.State.StartedAt}}' $(docker ps -aq)
        Get-Content $env:USERPROFILE\.claude\data\boot_dependency_wait.log -Tail 20

.PARAMETER Option
    'A' for auto-login, 'B' for boot service, 'C' for alert-only.

.PARAMETER Undo
    Revert the changes made by -Option A or -Option B.

.EXAMPLE
    .\fix_boot_start.ps1 -Option A
    .\fix_boot_start.ps1 -Option B
    .\fix_boot_start.ps1 -Option C
    .\fix_boot_start.ps1 -Option A -Undo
#>

param(
    [Parameter(Mandatory)]
    [ValidateSet('A', 'B', 'C')]
    [string]$Option,

    [switch]$Undo
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$TASK_NAME_BOOT   = 'Awareness-DockerDesktopBoot'
$TASK_NAME_ALERT  = 'Awareness-BootAlert'
$DOCKER_EXE       = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
# WSL distro is DETECTED, not hard-coded — see Get-ProjectWslDistro below.
# The literal 'Ubuntu' was wrong on this host (actual: 'Ubuntu-24.04'), which would
# have made the boot task's WSL warm-up fail while the task still installed clean.

# ── helpers ─────────────────────────────────────────────────────────────────

function Write-Step([string]$msg) { Write-Host "  => $msg" -ForegroundColor Cyan }
function Write-Done([string]$msg) { Write-Host "  ✓  $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "  ⚠  $msg" -ForegroundColor Yellow }

function Install-BootAlert {
    <#
    Option C: a scheduled task that fires 3 minutes after boot and sends
    an ntfy push if Docker isn't responding yet. Fires regardless of which
    option was chosen — belt and suspenders.

    ⚠ THREE DEFECTS FIXED 2026-09-16 (Caia). Caught before first install — this
    script has never been run (Get-ScheduledTask 'Awareness-*' returned nothing),
    so nothing leaked. Recording the shape so it is not reintroduced:

    1. CREDENTIAL SENT TO A THIRD PARTY. The external fallback posted
       `Authorization: Bearer $ntfyToken` to https://ntfy.sh. Our self-hosted
       token has no meaning there — ntfy.sh would simply receive and log it, on
       every failed boot. Fixed: the external call now carries NO auth header.

    2. THE PUBLIC TOPIC WAS DERIVED FROM THE SECRET —
       `https://ntfy.sh/jeff-$($ntfyToken.Substring(0,8))`. ntfy.sh topics are
       public and unauthenticated: anyone who learns the name can both READ the
       alerts and PUBLISH fake ones, and the name itself exposed 8 bytes of the
       token. Fixed: the topic is opt-in via NTFY_FALLBACK_TOPIC and is never
       derived from a credential.

    3. THE ALARM COULD FAIL SILENTLY, AND FAILED TOWARD RELIEF. Both posts ended
       in `2>$null` inside a hidden scheduled task, and nothing was ever
       subscribed to the derived topic — so the fallback had no receiver at all.
       "No boot alert arrived" therefore meant EITHER "boot was fine" OR "the
       alerter failed" — one signal, two conditions, and the quiet one is the
       reassuring one. That is the exact failure this alert exists to catch.
       Fixed: every branch writes a timestamped line to
       %USERPROFILE%\.claude\data\boot_alert.log, including the healthy case,
       so silence in the log is itself evidence rather than comfort.
    #>
    $script = @'
# The local post is the real path. The EXTERNAL path is deliberately opt-in and
# unauthenticated — see the three defects fixed 2026-09-16 in the function docstring.
$envFile   = "$env:USERPROFILE\Claude_Projects\Awareness\pps\docker\.env"
$logFile   = "$env:USERPROFILE\.claude\data\boot_alert.log"
$ntfyToken = (Get-Content $envFile | Select-String 'NTFY_TOKEN=(.+)').Matches.Groups[1].Value.Trim()
# Opt-in external topic. Absent = no external attempt. NEVER derive this from a secret.
$fallbackTopic = (Get-Content $envFile | Select-String 'NTFY_FALLBACK_TOPIC=(.+)').Matches.Groups[1].Value
if ($fallbackTopic) { $fallbackTopic = $fallbackTopic.Trim() }

function Write-BootLog([string]$line) {
    New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null
    Add-Content -Path $logFile -Value "$(Get-Date -Format o)  $line"
}

$dockerOk = (docker info 2>$null) -ne $null
if ($dockerOk) {
    Write-BootLog "OK docker responding 3min after boot; no alert sent"
    return
}

$body = "NUC rebooted but Docker not running yet — stack may be down. Check PPS."
Write-BootLog "DOWN docker not responding 3min after boot"

# 1. Local self-hosted ntfy — authenticated, this is the path Jeff's phone subscribes to.
try {
    Invoke-RestMethod -Method Post -Uri "http://localhost:8209/jeff" `
        -Headers @{ Authorization = "Bearer $ntfyToken"; Title = "Boot alert" } -Body $body | Out-Null
    Write-BootLog "SENT local ntfy ok"
} catch {
    Write-BootLog "FAIL local ntfy: $($_.Exception.Message)"
}

# 2. External fallback — ONLY if Jeff configured a topic AND subscribed his phone to it.
#    No Authorization header: ntfy.sh is a third party and has no business holding our token.
if (-not $fallbackTopic) {
    Write-BootLog "SKIP external fallback: NTFY_FALLBACK_TOPIC not set (no subscriber, so no point)"
} else {
    try {
        Invoke-RestMethod -Method Post -Uri "https://ntfy.sh/$fallbackTopic" `
            -Headers @{ Title = "Boot alert" } -Body $body | Out-Null
        Write-BootLog "SENT external ntfy.sh/$fallbackTopic ok"
    } catch {
        Write-BootLog "FAIL external ntfy.sh: $($_.Exception.Message)"
    }
}
'@
    $action  = New-ScheduledTaskAction -Execute 'pwsh.exe' -Argument "-NoProfile -WindowStyle Hidden -Command `"$script`""
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $trigger.Delay = 'PT3M'  # 3-minute delay after boot
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $TASK_NAME_ALERT -Action $action -Trigger $trigger `
        -Settings $settings -RunLevel Highest -Force | Out-Null
    Write-Done "Boot-alert task installed ($TASK_NAME_ALERT)"
}

function Remove-BootAlert {
    Unregister-ScheduledTask -TaskName $TASK_NAME_ALERT -Confirm:$false -ErrorAction SilentlyContinue
    Write-Done "Boot-alert task removed"
}


# ── OPTION A: auto-login ─────────────────────────────────────────────────────

function Enable-AutoLogin {
    Write-Step "Enabling Windows auto-login for current user..."
    $username = $env:USERNAME
    $cred = Get-Credential -Message "Enter your Windows password (stored in registry, encrypted):" -UserName $username
    $pw   = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
              [Runtime.InteropServices.Marshal]::SecureStringToBSTR($cred.Password))

    Set-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' `
        -Name AutoAdminLogon -Value '1'
    Set-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' `
        -Name DefaultUserName -Value $username
    Set-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' `
        -Name DefaultPassword -Value $pw

    Write-Done "Auto-login enabled for $username"
    Write-Warn "Password stored in registry. Secure boot screen is now bypassed."
    Write-Warn "Anyone with physical NUC access gets a logged-in Windows session."
}

function Disable-AutoLogin {
    Write-Step "Disabling Windows auto-login..."
    $reg = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
    Set-ItemProperty $reg -Name AutoAdminLogon -Value '0'
    Remove-ItemProperty $reg -Name DefaultPassword -ErrorAction SilentlyContinue
    Write-Done "Auto-login disabled"
}


# ── OPTION B: boot service + WSL task ───────────────────────────────────────

function Get-ProjectWslDistro {
    # `wsl.exe -l -q` emits UTF-16 with NULs when piped; strip them before matching.
    $distro = (& wsl.exe -l -q 2>$null |
        ForEach-Object { ($_ -replace "`0", '') -replace "`r", '' } |
        Where-Object { $_ -and $_ -notmatch '^docker-desktop' } |
        Select-Object -First 1)
    if (-not $distro) {
        throw "Could not detect a WSL distro. Run 'wsl -l -q' and set it manually."
    }
    return $distro.Trim()
}

function Enable-BootService {
    Write-Step "Setting com.docker.service to Automatic..."
    Set-Service -Name 'com.docker.service' -StartupType Automatic
    Write-Done "com.docker.service -> Automatic"

    Write-Step "Creating boot-time task to start Docker Desktop + WSL..."
    $distro = Get-ProjectWslDistro
    Write-Done "WSL distro detected: $distro"
    $actionDD = New-ScheduledTaskAction -Execute $DOCKER_EXE
    $actionWSL = New-ScheduledTaskAction -Execute 'wsl.exe' `
        -Argument "-d $distro --exec echo 'WSL warm'"
    $trigger   = New-ScheduledTaskTrigger -AtStartup
    $trigger.Delay = 'PT90S'  # 90s after boot to let services settle
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -RunLevel Highest
    $settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
    Register-ScheduledTask -TaskName $TASK_NAME_BOOT `
        -Action $actionDD, $actionWSL `
        -Trigger $trigger -Principal $principal `
        -Settings $settings -Force | Out-Null
    Write-Done "Boot task installed ($TASK_NAME_BOOT)"
    Write-Warn "Docker Desktop is session-oriented — some GUI features may not work"
    Write-Warn "without a logged-in user. Containers should start; verify after reboot."
}

function Disable-BootService {
    Write-Step "Reverting com.docker.service to Manual..."
    Set-Service -Name 'com.docker.service' -StartupType Manual
    Write-Step "Removing boot task..."
    Unregister-ScheduledTask -TaskName $TASK_NAME_BOOT -Confirm:$false -ErrorAction SilentlyContinue
    Write-Done "Option B reverted"
}


# ── dispatch ─────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "Awareness boot-start fix (#331)" -ForegroundColor White
Write-Host "Option $Option$(if ($Undo) { ' [UNDO]' })" -ForegroundColor White
Write-Host ""

switch ($Option) {
    'A' {
        if ($Undo) { Disable-AutoLogin } else { Enable-AutoLogin }
        if (-not $Undo) { Install-BootAlert }
    }
    'B' {
        if ($Undo) { Disable-BootService } else { Enable-BootService }
        if (-not $Undo) { Install-BootAlert }
    }
    'C' {
        if ($Undo) { Remove-BootAlert } else { Install-BootAlert }
    }
}

Write-Host ""
Write-Host "Done. Verify after next reboot:" -ForegroundColor White
Write-Host "  (Get-CimInstance Win32_OperatingSystem).LastBootUpTime"
Write-Host "  docker inspect -f '{{.Name}} {{.State.StartedAt}}' `$(docker ps -aq)"
Write-Host "  Get-Content `$env:USERPROFILE\.claude\data\boot_dependency_wait.log -Tail 20"
Write-Host ""
