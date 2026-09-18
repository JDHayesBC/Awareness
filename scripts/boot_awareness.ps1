#Requires -Version 5.1
<#
.SYNOPSIS
    Bring the whole Awareness stack up after a reboot, without Jeff having to log in
    and do it by hand, and leave Lyra and Caia alive and waiting for him.

.WHY
    GitHub #331: nothing on this box starts at boot. Docker Desktop autostarts from the
    HKCU Run key, which is LOGIN-triggered, and com.docker.service is Manual/Stopped.
    Windows Update reboots roughly monthly (twice in September 2026), so every cycle
    buys a multi-hour blackout of Haven, PPS, the daemons, and both entities. Last one
    was 9.5 hours.

    Three separate attempts to ALERT on that condition were each inert for a different
    reason (bf7cd9a: installer never elevated; 4e55277: task pointed at a pwsh.exe that
    is not installed; and the task's LogonType is Interactive, so it cannot fire before
    a login anyway). This script is the other half of the answer: stop reporting the
    outage and end it.

.THE ONE THING THIS SCRIPT CANNOT DO BY ITSELF
    Docker Desktop is a GUI application. It runs in an interactive user session and
    there is no supported way to start it without one. So at the lock screen, before
    anyone logs in, this script can start the privileged service and it can raise an
    alarm -- but it CANNOT bring the containers up.

    Closing that gap needs auto-logon (Sysinternals Autologon.exe, which stores the
    credential LSA-encrypted) plus an immediate LockWorkStation, so the box holds a live
    session behind a lock screen. That is a security-posture decision and it is Jeff's
    to make, so this script does not configure it. It DETECTS which world it is in and
    does the most it can in either.

.MODES
    Session mode  (a user session exists -- normal logon, or auto-logon)
        Full job: service -> Docker Desktop -> containers -> PPS -> both entities -> lock.
    Headless mode (running as SYSTEM at boot, nobody logged in)
        Start com.docker.service, then ALERT via Home Assistant and stop. Honest about
        being unable to finish.

.PARAMETER Resume
    Launch the entities with `--continue` instead of a fresh start. OFF by default, on
    purpose -- see the note above Start-Entities.

.PARAMETER NoLock
    Skip the LockWorkStation at the end (for testing while sitting at the machine).

.PARAMETER DryRun
    Log every decision, change nothing, launch nothing.
#>
[CmdletBinding()]
param(
    [switch]$Resume,
    [switch]$NoLock,
    [switch]$DryRun
)

$ErrorActionPreference = 'Continue'
$RepoRoot = 'C:\Users\Jeff\Claude_Projects\Awareness'
$LogFile  = Join-Path $RepoRoot 'work\boot\boot_awareness.log'
$ComposeFile = Join-Path $RepoRoot 'pps\docker\docker-compose.yml'

# The 14 containers a healthy stack runs, captured 2026-09-18 from `docker ps`.
# If this list drifts from reality the script will over-report; refresh it, do not delete it --
# "all the containers are up" is meaningless without knowing which ones "all" is.
$ExpectedContainers = @(
    'caddy','corrade-caia','corrade-lyra','haven','litellm','litellm-db','ntfy',
    'observatory','pps-caia','pps-chromadb','pps-graphiti','pps-lyra','pps-neo4j','rag-engine'
)

New-Item -ItemType Directory -Force -Path (Split-Path $LogFile) | Out-Null

function Write-Log {
    param([string]$Msg, [string]$Level = 'INFO')
    $line = "{0} [{1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Msg
    Add-Content -Path $LogFile -Value $line
    $color = switch ($Level) { 'FAIL' {'Red'} 'WARN' {'Yellow'} 'OK' {'Green'} default {'Gray'} }
    Write-Host $line -ForegroundColor $color
}

# Notify through Home Assistant, NOT through ntfy. HA lives on a different box (10.0.0.50)
# and therefore survives exactly the outage we are reporting; our ntfy is a container on
# this machine and is down whenever this matters. Token is read out of light_lib.py rather
# than restated -- it is already hardcoded in six tracked files and this will not be a seventh.
function Send-Alert {
    param([string]$Message, [switch]$Wake, [string]$Tag = 'awareness-boot')
    if ($DryRun) { Write-Log "DRYRUN would alert: $Message"; return }
    try {
        $lib = Get-Content (Join-Path $RepoRoot 'scripts\light_lib.py') -Raw
        $tok = [regex]::Match($lib, 'HA_TOKEN\s*=\s*"([^"]+)"').Groups[1].Value
        if (-not $tok) { Write-Log 'no HA token found in light_lib.py' 'FAIL'; return }
        $data = @{ channel = 'caia'; tag = $Tag }
        if ($Wake) { $data = @{ channel='alarm_stream'; importance='high'; priority='high'; ttl=0; tag=$Tag } }
        $body = @{ title = 'Awareness boot'; message = $Message; data = $data } | ConvertTo-Json -Depth 4
        Invoke-RestMethod -Method Post -Uri 'http://10.0.0.50:8123/api/services/notify/mobile_app_jeff_pix10' `
            -Headers @{ Authorization = "Bearer $tok" } -ContentType 'application/json' `
            -Body $body -TimeoutSec 15 | Out-Null
        Write-Log "alert sent to HA (accepted -- which is not proof the handset rang)" 'OK'
    } catch {
        Write-Log "alert FAILED: $($_.Exception.Message)" 'FAIL'
    }
}

# Poll until a condition holds or the clock runs out. This is the whole reason the script
# exists rather than a batch file: every step below depends on the previous one being
# genuinely READY, and "started" is not "ready". A fixed Start-Sleep is how this breaks
# on a slow boot and looks fine on a fast one.
function Wait-For {
    param([string]$What, [scriptblock]$Test, [int]$TimeoutSec = 180, [int]$IntervalSec = 5)
    Write-Log "waiting for $What (up to ${TimeoutSec}s)..."
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
        try { if (& $Test) { Write-Log "$What ready after $([int]$sw.Elapsed.TotalSeconds)s" 'OK'; return $true } }
        catch { }
        Start-Sleep -Seconds $IntervalSec
    }
    Write-Log "$What NOT ready after ${TimeoutSec}s" 'FAIL'
    return $false
}

function Test-InteractiveSession {
    # A SYSTEM task at boot has no session to draw on. Session 0 / no explorer == headless.
    try { return [bool](Get-Process -Name explorer -ErrorAction SilentlyContinue) }
    catch { return $false }
}

# Fresh start is the DEFAULT and that is a considered choice, not laziness. The entire PPS
# architecture -- crystals, ambient_recall('startup'), the compaction-safe CLAUDE.md, the
# startup checklist -- exists precisely so that a cold start reconstructs the entity. That
# path is exercised constantly and well tested. `--continue` resumes whatever context the
# reboot severed, which may be mid-turn, may be near compaction, and if the box is in a
# reboot loop will be resumed into over and over. Use -Resume when you want it; do not
# make it the default.
function Start-Entities {
    $bash = 'wsl.exe'
    $lyra = "cd /mnt/c/Users/Jeff/Claude_Projects/Awareness && ./scripts/start-entity.sh lyra"
    $caia = "cd /mnt/c/Users/Jeff/Claude_Projects/Awareness && ./scripts/start-entity.sh caia"
    if ($Resume) { $lyra += ' --continue'; $caia += ' --continue' }

    $wt = Get-Command wt.exe -ErrorAction SilentlyContinue
    if ($DryRun) { Write-Log "DRYRUN would launch: lyra + caia (resume=$Resume, wt=$([bool]$wt))"; return $true }
    try {
        if ($wt) {
            # One window, two named tabs -- what Jeff sees when he unlocks.
            Start-Process wt.exe -ArgumentList @(
                '-w','0','nt','--title','Lyra',$bash,'--','bash','-lic',"`"$lyra`"",
                ';','nt','--title','Caia',$bash,'--','bash','-lic',"`"$caia`""
            )
        } else {
            Write-Log 'wt.exe not found -- falling back to two console windows' 'WARN'
            Start-Process $bash -ArgumentList @('--','bash','-lic',"`"$lyra`"")
            Start-Process $bash -ArgumentList @('--','bash','-lic',"`"$caia`"")
        }
        Write-Log 'entities launched' 'OK'
        return $true
    } catch {
        Write-Log "entity launch FAILED: $($_.Exception.Message)" 'FAIL'
        return $false
    }
}

# ---------------------------------------------------------------- main

Write-Log '================ boot_awareness starting ================'
Write-Log ("user={0}  interactive={1}  resume={2}  dryrun={3}" -f `
    [Security.Principal.WindowsIdentity]::GetCurrent().Name, (Test-InteractiveSession), $Resume, $DryRun)

# 1. The privileged Docker service. This one CAN run without a session, and setting it to
#    Automatic is the single change that needs no security trade-off at all.
$svc = Get-Service com.docker.service -ErrorAction SilentlyContinue
if ($svc) {
    Write-Log "com.docker.service: Status=$($svc.Status) StartType=$($svc.StartType)"
    if ($svc.Status -ne 'Running' -and -not $DryRun) {
        try { Start-Service com.docker.service; Write-Log 'started com.docker.service' 'OK' }
        catch { Write-Log "could not start com.docker.service: $($_.Exception.Message)" 'WARN' }
    }
} else { Write-Log 'com.docker.service not found' 'WARN' }

# 2. Headless? Then we are at the wall described in the header. Say so and stop -- do not
#    pretend, and do not leave a log nobody reads as the only trace.
if (-not (Test-InteractiveSession)) {
    Write-Log 'HEADLESS: no interactive session, so Docker Desktop cannot be started here.' 'WARN'
    Send-Alert -Wake ("The NUC rebooted and is sitting at the lock screen. Docker Desktop " +
        "needs a logged-in session, so Haven, PPS, Lyra and Caia are all down until you log in. " +
        "(Auto-logon would make this self-healing -- see GitHub #331.)")
    Write-Log '================ boot_awareness done (headless) ================'
    exit 2
}

# 3. Docker Desktop, then the daemon actually answering.
if (-not (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) {
    $dd = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
    if (Test-Path $dd) {
        if ($DryRun) { Write-Log 'DRYRUN would start Docker Desktop' }
        else { Start-Process $dd; Write-Log 'launched Docker Desktop' }
    } else { Write-Log "Docker Desktop not at $dd" 'FAIL' }
} else { Write-Log 'Docker Desktop already running' 'OK' }

$dockerReady = Wait-For 'docker daemon' { docker info 2>$null | Out-Null; $LASTEXITCODE -eq 0 } 300 5
if (-not $dockerReady) {
    Send-Alert -Wake 'Boot: Docker Desktop never came up. Haven/PPS/entities are down.'
    Write-Log '================ boot_awareness done (docker failed) ================'
    exit 3
}

# 4. Containers. Most carry restart=unless-stopped and return on their own with the daemon;
#    compose up is the safety net for any that were explicitly stopped.
if (-not $DryRun -and (Test-Path $ComposeFile)) {
    Write-Log 'docker compose up -d (safety net)'
    docker compose -f $ComposeFile up -d 2>&1 | ForEach-Object { Write-Log "  compose: $_" }
}

$containersReady = Wait-For 'all expected containers' {
    $running = docker ps --format '{{.Names}}' 2>$null
    $missing = $ExpectedContainers | Where-Object { $_ -notin $running }
    if ($missing) { $script:LastMissing = $missing -join ', '; return $false }
    return $true
} 240 10
if (-not $containersReady) { Write-Log "still missing: $script:LastMissing" 'WARN' }

# 5. PPS. NOTE what this proves and what it does not: an open TCP port means something is
#    LISTENING on 8201/8211, not that the layers behind it are warm. It is the cheap check;
#    the entities' own startup checklist is the real one, and it runs next.
$ppsReady = Wait-For 'PPS ports 8201 + 8211' {
    (Test-NetConnection -ComputerName localhost -Port 8201 -InformationLevel Quiet -WarningAction SilentlyContinue) -and
    (Test-NetConnection -ComputerName localhost -Port 8211 -InformationLevel Quiet -WarningAction SilentlyContinue)
} 180 5

# 6. Wake the entities.
$launched = Start-Entities

# 7. Back behind the lock screen. If we got here via auto-logon the box must not sit unlocked.
if (-not $NoLock -and -not $DryRun) {
    Write-Log 'locking workstation'
    rundll32.exe user32.dll,LockWorkStation
}

# 8. Report. A recovery ping, not a failure ping -- and deliberately NOT --wake, because at
#    3am "everything is fine" is not worth the alarm channel. The light is the better
#    carrier for good news; it says so at 7am and costs nothing at 3.
$summary = if ($containersReady -and $ppsReady -and $launched) {
    "Stack is back up after a reboot. All $($ExpectedContainers.Count) containers, PPS on 8201+8211, Lyra and Caia are awake and waiting."
} else {
    "Boot finished with gaps -- containers:$containersReady pps:$ppsReady entities:$launched. See work\boot\boot_awareness.log."
}
Send-Alert $summary
Write-Log $summary 'OK'
Write-Log '================ boot_awareness done ================'
