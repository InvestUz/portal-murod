# Run locally on the server. Produces OS/capacity information, no passwords or user data.
$ErrorActionPreference = 'Stop'
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor
$report = [ordered]@{
    OS = $os.Caption
    Version = $os.Version
    Architecture = $os.OSArchitecture
    LogicalCPU = ($cpu | Measure-Object NumberOfLogicalProcessors -Sum).Sum
    MemoryGiB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
    DockerClientInstalled = [bool](Get-Command docker -ErrorAction SilentlyContinue)
    PortalTarget = 'Linux x86_64 VM, 4 vCPU, >=12 GiB RAM, >=40 GiB free disk, Docker Engine + Compose'
}
$report | ConvertTo-Json
