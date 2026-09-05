<#
    Internet health monitor (Windows-native twin of scripts/net_health_monitor.py)

    Pings Cloudflare (1.1.1.1) and Google (8.8.8.8), records packet loss %,
    average round-trip (ms), and jitter (stdev of the individual replies, ms),
    then writes ONE human-readable line per sample in the exact same format as
    the NUC's Linux log so the two can be compared side-by-side:

        2026-09-02 13:05:01 PDT | 1.1.1.1: loss=20.0% avg=22ms jit=9ms | 8.8.8.8: loss=20.0% avg=23ms jit=11ms | DEGRADED

    Overall status per sample = the WORST of the two targets:
        OK        loss < 5%,  avg < 100 ms, jitter < 40 ms
        DEGRADED  loss 5-99%, or high latency / jitter
        DOWN      100% loss / unreachable

    Purpose: run this on the WIRED desktop while the NUC logs over WiFi. If the
    wired box stays clean and the NUC is lossy -> WiFi. If BOTH are lossy at the
    same timestamps -> the line (Shaw/Rogers), which is the bet.

    Design notes:
      * Parses per-reply "time=NNms" tokens only (counts replies for loss,
        computes avg + jitter from them). Avoids Windows ping's LOCALIZED
        summary strings ("Lost =", "Average =") so it works on any language.
      * Takes ONE sample and exits -> schedule it every 5 min with Task
        Scheduler (cleaner on Windows than a forever-loop).
      * Pure PowerShell, no admin needed. Log is written next to this script.
      * IMPORTANT: copy this file to a LOCAL folder on the wired desktop before
        installing -- do NOT run it from the shared NUC drive, or its log will
        interleave with the NUC's own internet_health.log and muddy the A/B test.
        Each machine must write its OWN local log; you compare the two by hand.

    Install (run once, from an elevated-optional PowerShell in this folder):

      $action  = New-ScheduledTaskAction -Execute "powershell.exe" `
                   -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PWD\net_health_monitor.ps1`""
      $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
                   -RepetitionInterval (New-TimeSpan -Minutes 5)
      Register-ScheduledTask -TaskName "NetHealthMonitor" -Action $action `
                   -Trigger $trigger -Description "Wired-desktop net health twin"

    Test a single sample by hand:
      powershell -NoProfile -ExecutionPolicy Bypass -File .\net_health_monitor.ps1
#>

$ErrorActionPreference = 'Stop'

# ---- config (mirrors the Python twin) --------------------------------------
$LogPath        = Join-Path $PSScriptRoot 'internet_health.log'
$Targets        = @('1.1.1.1', '8.8.8.8')
$PingCount      = 20        # packets per target -> 5% loss granularity
$LossDegraded   = 5.0       # percent
$RttDegraded    = 100.0     # ms average
$JitterDegraded = 40.0      # ms stdev

$WorstRank = @{ 'OK' = 0; 'DEGRADED' = 1; 'ERROR' = 2; 'DOWN' = 3 }

function Measure-Target {
    param([string]$Host_)

    $rtts = New-Object System.Collections.Generic.List[double]
    try {
        # -w 1000 = 1s wait per ping. Without it, each LOST packet blocks for the
        # 4s Windows default, so a lossy window can stretch one sample to minutes
        # of silent "blinking". This caps a 20-ping target at ~20s even at 100% loss.
        $out = ping.exe -n $PingCount -w 1000 $Host_ 2>$null
    } catch {
        return @{ status = 'ERROR'; loss = $null; avg = $null; jitter = $null }
    }

    foreach ($line in $out) {
        # "Reply from 1.1.1.1: bytes=32 time=22ms TTL=55"  /  "time<1ms"
        if ($line -match 'time[=<]\s*(\d+)\s*ms') {
            $val = [double]$Matches[1]
            if ($line -match 'time<') { $val = 0.0 }   # <1ms -> ~0
            $rtts.Add($val)
        }
    }

    $received = $rtts.Count
    $loss = (($PingCount - $received) / $PingCount) * 100.0

    if ($received -eq 0) {
        return @{ status = 'DOWN'; loss = 100.0; avg = $null; jitter = $null }
    }

    $avg = ($rtts | Measure-Object -Average).Average
    # jitter = population stdev of the replies (proxy for ping's mdev)
    $mean = $avg
    $var  = 0.0
    foreach ($r in $rtts) { $var += [math]::Pow($r - $mean, 2) }
    $jitter = [math]::Sqrt($var / $received)

    if ($loss -ge 100.0) {
        $status = 'DOWN'
    } elseif ($loss -ge $LossDegraded -or $avg -ge $RttDegraded -or $jitter -ge $JitterDegraded) {
        $status = 'DEGRADED'
    } else {
        $status = 'OK'
    }

    return @{ status = $status; loss = $loss; avg = $avg; jitter = $jitter }
}

function Format-Target {
    param([string]$Host_, [hashtable]$R)
    $loss_s = if ($null -ne $R.loss)   { '{0:0.0}%' -f $R.loss }   else { '?' }
    $avg_s  = if ($null -ne $R.avg)    { '{0:0}ms'  -f $R.avg }    else { '--' }
    $jit_s  = if ($null -ne $R.jitter) { '{0:0}ms'  -f $R.jitter } else { '--' }
    return "{0}: loss={1} avg={2} jit={3}" -f $Host_, $loss_s, $avg_s, $jit_s
}

# ---- take one sample -------------------------------------------------------
$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
if ([System.TimeZoneInfo]::Local.IsDaylightSavingTime((Get-Date))) {
    $tz = [System.TimeZoneInfo]::Local.DaylightName
} else {
    $tz = [System.TimeZoneInfo]::Local.StandardName
}
# Compact TZ abbreviation (e.g. "Pacific Daylight Time" -> "PDT")
$tzAbbr = -join ($tz -split '\s+' | ForEach-Object { $_.Substring(0,1) })

$parts    = @()
$statuses = @()
foreach ($host_ in $Targets) {
    $r = Measure-Target -Host_ $host_
    $statuses += $r.status
    $parts    += (Format-Target -Host_ $host_ -R $r)
}

$overall = $statuses | Sort-Object { $WorstRank[$_] } -Descending | Select-Object -First 1
$line = "{0} {1} | {2} | {3}" -f $ts, $tzAbbr, ($parts -join ' | '), $overall

try {
    Add-Content -Path $LogPath -Value $line -Encoding utf8
} catch {
    Write-Error "log write failed: $_"
}

Write-Output $line
