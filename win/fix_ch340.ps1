# Fix the CH340 "CM_PROB_FAILED_ADD / COM port collision" problem.
#
# Symptom: Device Manager shows "USB-SERIAL CH340 (COMn)" with a yellow mark,
# status Error, problem 0x1F, status 0xC0000035 (STATUS_OBJECT_NAME_COLLISION) --
# Windows handed it a COM number that a Bluetooth serial port already owns, so the
# serial driver never creates the port. No COM port exists at all, so the overlay
# just waits forever.
#
# This script picks a high, genuinely free COM number (>= 20), writes it to the
# device's PortName, restarts the device, and reports the result.
# Re-run it any time the adapter gets a colliding number again (new USB port, reboot).
#
# Usage: double-click fix_ch340.bat  (it self-elevates through UAC)

$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = Join-Path $here "fix_ch340.log"

function W($m) { "$m" | Out-File -FilePath $log -Append -Encoding utf8 }

# --- self-elevate -----------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    "" | Out-File -FilePath $log -Encoding utf8
    W "relaunching elevated: $PSCommandPath"
    $args = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Start-Process powershell -Verb RunAs -ArgumentList $args -Wait
    Get-Content $log -Tail 40
    exit
}

"" | Out-File -FilePath $log -Encoding utf8
W "start $(Get-Date -Format o)  admin=$isAdmin"

# --- find CH340 instances ---------------------------------------------------
$base = "HKLM:\SYSTEM\CurrentControlSet\Enum\USB\VID_1A86&PID_7523"
$instances = Get-ChildItem $base -ErrorAction SilentlyContinue | ForEach-Object { $_.PSChildName }
if (-not $instances) { W "no CH340 (VID_1A86&PID_7523) found - is the USB-TTL plugged in?"; Get-Content $log; exit 1 }

# COM names already in use (bluetooth ports etc.)
$used = @()
$sc = Get-ItemProperty "HKLM:\HARDWARE\DEVICEMAP\SERIALCOMM" -ErrorAction SilentlyContinue
if ($sc) {
    $used = $sc.PSObject.Properties | Where-Object { $_.Name -notlike "PS*" } | ForEach-Object { $_.Value }
}
W ("COM in use: " + ($used -join ", "))

foreach ($name in $instances) {
    $inst = "USB\VID_1A86&PID_7523\$name"
    $dev = Get-PnpDevice -InstanceId $inst -ErrorAction SilentlyContinue
    W "instance $name  status=$($dev.Status)  problem=$($dev.Problem)  name=$($dev.FriendlyName)"
    if ($dev.Problem -ne "CM_PROB_FAILED_ADD" -and $dev.Status -ne "Error") {
        W "  not a COM-collision failure, skip"
        continue
    }

    # pick the lowest free number >= 20
    $target = $null
    for ($n = 20; $n -le 40; $n++) {
        if ($used -notcontains "COM$n") { $target = "COM$n"; break }
    }
    if (-not $target) { W "no free COM in 20..40"; continue }

    $reg = "HKLM:\SYSTEM\CurrentControlSet\Enum\$inst\Device Parameters"
    try {
        Set-ItemProperty -Path $reg -Name PortName -Value $target -ErrorAction Stop
        W "  PortName -> $target"
        $used += $target
    } catch {
        W "  set PortName failed: $($_.Exception.Message)"
        continue
    }
    (pnputil /restart-device "$inst" 2>&1) | ForEach-Object { W "  $_" }
    Start-Sleep -Seconds 2
    $dev2 = Get-PnpDevice -InstanceId $inst -ErrorAction SilentlyContinue
    W "  after restart: status=$($dev2.Status) problem=$($dev2.Problem) name=$($dev2.FriendlyName)"
}

W "--- serial ports now ---"
$sc2 = Get-ItemProperty "HKLM:\HARDWARE\DEVICEMAP\SERIALCOMM" -ErrorAction SilentlyContinue
if ($sc2) { $sc2.PSObject.Properties | Where-Object { $_.Name -notlike "PS*" } | ForEach-Object { W ("  {0} -> {1}" -f $_.Name, $_.Value) } }
W "done"
Get-Content $log