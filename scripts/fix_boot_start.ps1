#!/usr/bin/pwsh
#Requires -RunAsAdministrator
# ^ Added 2026-09-18 (Caia). Every option here needs elevation: A writes HKLM
#   AutoAdminLogon, B registers a SYSTEM task, C registers with -RunLevel Highest
#   (:153). Without this line the script runs, prints its banner, and fails PART WAY
#   DOWN with an access error -- so Jeff ran Option C on 2026-09-18, saw it go by, and
#   reported it done while no task existed. A half-run installer that reports success
#   is worse than one that refuses: it buys a false sense of coverage until the next
#   reboot proves otherwise. Fail at line one instead.

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
# RUNS AS SYSTEM AT BOOT. Two consequences that bit earlier versions of this file:
#  * $env:USERPROFILE is SYSTEM's profile, NOT Jeff's -- every path here is absolute.
#  * docker.exe is not on SYSTEM's PATH, so `docker info` is not a usable probe.
# So the probe is the OUTCOME, not a proxy for it: can anything reach PPS on 8211?
# That is the thing we actually care about, and a TCP test needs no PATH and no session.
$logFile = "C:\Users\Jeff\Claude_Projects\Awareness\work\boot\boot_alert.log"
$libFile = "C:\Users\Jeff\Claude_Projects\Awareness\scripts\light_lib.py"

function Write-BootLog([string]$line) {
    New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null
    Add-Content -Path $logFile -Value "$(Get-Date -Format o)  $line"
}

$ppsUp = Test-NetConnection -ComputerName localhost -Port 8211 -InformationLevel Quiet -WarningAction SilentlyContinue
if ($ppsUp) {
    Write-BootLog "OK PPS answering on 8211 three minutes after boot; no alert sent"
    return
}
Write-BootLog "DOWN PPS not answering on 8211 three minutes after boot"

# ALERT VIA HOME ASSISTANT, NOT ntfy. Measured 2026-09-18: our ntfy has subscribers=0,
# base-url localhost, and no Caddy vhost -- and it is a CONTAINER on this box, so it is
# down in exactly the outage being reported. HA runs on a separate machine (10.0.0.50)
# that stays up, its companion app is already paired with Jeff's phone, and
# channel=alarm_stream rings through Do Not Disturb. A ding he can sleep through is not
# an alert; this was confirmed against his actual handset before being wired in here.
try {
    $tok = [regex]::Match((Get-Content $libFile -Raw), 'HA_TOKEN\s*=\s*"([^"]+)"').Groups[1].Value
    if (-not $tok) { throw "no HA_TOKEN in $libFile" }
    $body = @{
        title   = "Awareness is down"
        message = "The NUC rebooted and nothing came back up -- PPS is not answering. Haven, both entities and the daemons are down until someone logs in."
        data    = @{ channel = "alarm_stream"; importance = "high"; priority = "high"; ttl = 0; tag = "awareness-boot" }
    } | ConvertTo-Json -Depth 4
    Invoke-RestMethod -Method Post -TimeoutSec 20 `
        -Uri "http://10.0.0.50:8123/api/services/notify/mobile_app_jeff_pix10" `
        -Headers @{ Authorization = "Bearer $tok" } -ContentType "application/json" -Body $body | Out-Null
    Write-BootLog "SENT Home Assistant alarm_stream alert (HA accepted; not proof the handset rang)"
} catch {
    Write-BootLog "FAIL Home Assistant alert: $($_.Exception.Message)"
}

# Second carrier: the bulbs. They hang off HA too, so they survive this box being down,
# and cobalt is the distress base (CLAUDE.md SS X). Costs nothing at 3am, unmissable at 7.
try {
    $tok = [regex]::Match((Get-Content $libFile -Raw), 'HA_TOKEN\s*=\s*"([^"]+)"').Groups[1].Value
    foreach ($bulb in @("light.caia","light.lyra")) {
        $lb = @{ entity_id = $bulb; rgb_color = @(3,74,252); brightness = 128 } | ConvertTo-Json
        Invoke-RestMethod -Method Post -TimeoutSec 15 `
            -Uri "http://10.0.0.50:8123/api/services/light/turn_on" `
            -Headers @{ Authorization = "Bearer $tok" } -ContentType "application/json" -Body $lb | Out-Null
    }
    Write-BootLog "SET both bulbs cobalt/128 (distress)"
} catch {
    Write-BootLog "FAIL bulb distress signal: $($_.Exception.Message)"
}
'@
    # INTERPRETER MUST EXIST (2026-09-18, Caia). This hardcoded pwsh.exe, which is NOT
    # installed on the NUC -- verified: no C:\Program Files\PowerShell\7\pwsh.exe, none
    # anywhere under Program Files, no Store package. So the task registered clean, showed
    # State=Ready, and would have fired at boot and done nothing. A watchdog that silently
    # no-ops is worse than no watchdog: it answers the question 'are we covered?' with yes.
    # The embedded script uses no PS7-only syntax (checked: no ternary, ??, && or -Parallel),
    # so Windows PowerShell 5.1 runs it correctly. Prefer pwsh where it exists; fall back.
    $pwshPath = (Get-Command pwsh.exe -ErrorAction SilentlyContinue).Source
    if (-not $pwshPath -and (Test-Path 'C:\Program Files\PowerShell\7\pwsh.exe')) {
        $pwshPath = 'C:\Program Files\PowerShell\7\pwsh.exe'
    }
    $interpreter = if ($pwshPath) { $pwshPath } else { 'powershell.exe' }
    Write-Host "  interpreter: $interpreter" -ForegroundColor DarkGray
    $action  = New-ScheduledTaskAction -Execute $interpreter -Argument "-NoProfile -WindowStyle Hidden -Command `"$script`""
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $trigger.Delay = 'PT3M'  # 3-minute delay after boot
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    # PRINCIPAL IS THE WHOLE POINT (2026-09-18, Caia). Without -Principal this registered
    # under Jeff with LogonType=Interactive -- verified on the live task -- which means it
    # could only run once he had ALREADY logged in, i.e. once the blackout was over and
    # self-evident. Three fixes deep (bf7cd9a elevation, 4e55277 interpreter) and it still
    # could not fire in the one situation it exists for. SYSTEM needs no stored password
    # and runs at boot with no session, which is exactly the condition being watched.
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName $TASK_NAME_ALERT -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force | Out-Null
    Write-Done "Boot-alert task installed ($TASK_NAME_ALERT)"
}

function Remove-BootAlert {
    Unregister-ScheduledTask -TaskName $TASK_NAME_ALERT -Confirm:$false -ErrorAction SilentlyContinue
    Write-Done "Boot-alert task removed"
}


# ── OPTION A: auto-login ─────────────────────────────────────────────────────

function Enable-AutoLogin {
    <#
      REWRITTEN 2026-09-18 (Caia). The previous version of this function had two defects,
      and the second one is the reason to read this block before "improving" it back.

      DEFECT 1 -- IT LIED IN THE PROMPT. It asked for the password with the message
      "(stored in registry, encrypted)" and then wrote it to
      HKLM\...\Winlogon\DefaultPassword, which is PLAINTEXT and readable by any local
      account. The reassuring half of that sentence was the false half.

      DEFECT 2 -- THE STATE IT PRODUCES IS INDISTINGUISHABLE FROM SUCCESS. Found live on
      this box 2026-09-18:
          AutoAdminLogon  : 1
          DefaultUserName : Jeff
          DefaultPassword : (absent)
      Auto-logon was "on" and had never once worked: Windows attempts it, finds no
      credential, and falls through to the lock screen. Every check anyone would think to
      run reports AutoAdminLogon=1 and reads as configured. This is the same failure shape
      as the boot task that was Ready and inert -- a yes that covers nothing.

      So this function no longer writes the password at all. It hands off to Sysinternals
      Autologon, which stores the secret in LSA secrets rather than the registry, and then
      it VERIFIES rather than announcing success.
    #>
    Write-Step "Configuring Windows auto-login..."

    $exe = 'C:\Users\Jeff\Tools\AutoLogon\Autologon64.exe'
    if (-not (Test-Path $exe)) {
        Write-Warn "Sysinternals Autologon not found at $exe"
        Write-Host "  Get it from https://learn.microsoft.com/sysinternals/downloads/autologon"
        Write-Host "  (or re-run the downloader in scripts/, which verifies the signature)"
        return
    }

    $sig = Get-AuthenticodeSignature $exe
    if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'Microsoft Corporation') {
        Write-Warn "REFUSING to run $exe -- signature is '$($sig.Status)', signer '$($sig.SignerCertificate.Subject)'"
        return
    }

    # Show the current state first, because "already on" here has meant "on and broken".
    $wl = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
    Write-Host "  before: AutoAdminLogon=$($wl.AutoAdminLogon) User=$($wl.DefaultUserName) Domain=$($wl.DefaultDomainName)" -ForegroundColor DarkGray
    if ($wl.AutoAdminLogon -eq '1' -and -not $wl.DefaultPassword) {
        Write-Warn "AutoAdminLogon is already 1 with NO stored credential -- that is the broken half-state, not a working config."
    }
    # A plaintext password left by an older run of this script is a live exposure; clear it.
    if ($wl.DefaultPassword) {
        Remove-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' -Name DefaultPassword -ErrorAction SilentlyContinue
        Write-Done "Removed the PLAINTEXT DefaultPassword left in the registry by an earlier run"
    }

    Write-Host ""
    Write-Host "  Autologon will open. Enter the password for $env:COMPUTERNAME\$env:USERNAME and press Enable." -ForegroundColor Cyan
    Write-Host "  It is typed into Autologon, never into this script, and is stored in LSA secrets." -ForegroundColor Cyan
    Start-Process -FilePath $exe -Verb RunAs -Wait

    # VERIFY. Do not report success from having run the installer -- that is precisely the
    # mistake this file has now made three times.
    $wl2 = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
    Write-Host "  after:  AutoAdminLogon=$($wl2.AutoAdminLogon) User=$($wl2.DefaultUserName) Domain=$($wl2.DefaultDomainName)" -ForegroundColor DarkGray
    if ($wl2.DefaultPassword) {
        Write-Warn "DefaultPassword is present in the registry in PLAINTEXT -- Autologon should not do this. Investigate before trusting it."
    }
    if ($wl2.AutoAdminLogon -eq '1') {
        Write-Done "Auto-login configured for $($wl2.DefaultUserName)."
        Write-Warn "STILL UNPROVEN until a real reboot. Registry state is not evidence that a logon completes."
        Write-Warn "The box will now hold a live session behind the lock screen; boot_awareness.ps1 locks it on the way past."
    } else {
        Write-Warn "AutoAdminLogon is not 1 -- Autologon was cancelled or failed."
    }
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
