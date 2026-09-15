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
$WSL_DISTRO       = 'Ubuntu'  # adjust if Jeff's distro name differs

# ── helpers ─────────────────────────────────────────────────────────────────

function Write-Step([string]$msg) { Write-Host "  => $msg" -ForegroundColor Cyan }
function Write-Done([string]$msg) { Write-Host "  ✓  $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "  ⚠  $msg" -ForegroundColor Yellow }

function Install-BootAlert {
    <#
    Option C: a scheduled task that fires 3 minutes after boot and sends
    an ntfy push if Docker isn't responding yet. Fires regardless of which
    option was chosen — belt and suspenders.
    #>
    $script = @'
$ntfyToken = (Get-Content "$env:USERPROFILE\Claude_Projects\Awareness\pps\docker\.env" |
              Select-String 'NTFY_TOKEN=(.+)').Matches.Groups[1].Value.Trim()
$dockerOk  = (docker info 2>$null) -ne $null
if (-not $dockerOk) {
    $body = "NUC rebooted but Docker not running yet — stack may be down. Check PPS."
    Invoke-RestMethod -Method Post `
        -Uri "http://localhost:8209/jeff" `
        -Headers @{ Authorization = "Bearer $ntfyToken"; Title = "⚠ Boot alert" } `
        -Body $body 2>$null
    # Fall back to external ntfy.sh if local isn't up yet
    Invoke-RestMethod -Method Post `
        -Uri "https://ntfy.sh/jeff-$(($ntfyToken.Substring(0,8)))" `
        -Headers @{ Authorization = "Bearer $ntfyToken"; Title = "⚠ Boot alert" } `
        -Body $body 2>$null
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

function Enable-BootService {
    Write-Step "Setting com.docker.service to Automatic..."
    Set-Service -Name 'com.docker.service' -StartupType Automatic
    Write-Done "com.docker.service -> Automatic"

    Write-Step "Creating boot-time task to start Docker Desktop + WSL..."
    $actionDD = New-ScheduledTaskAction -Execute $DOCKER_EXE
    $actionWSL = New-ScheduledTaskAction -Execute 'wsl.exe' `
        -Argument "-d $WSL_DISTRO --exec echo 'WSL warm'"
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
