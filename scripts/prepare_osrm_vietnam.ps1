param(
    [string]$PbfUrl = "https://download.geofabrik.de/asia/vietnam-latest.osm.pbf",
    [string]$DataDirectory = "data/osrm",
    [string]$Image = "ghcr.io/project-osrm/osrm-backend:v26.6.5-debian",
    [string]$OsmiumImage = "p210-osmium-tool:1.15.0",
    [ValidateRange(1, 64)]
    [int]$OsrmThreads = 6,
    [switch]$PrepareRoutingInputOnly
)

$ErrorActionPreference = "Stop"
function Write-Utf8NoBom([string]$Path, [string]$Value) {
    [System.IO.File]::WriteAllText(
        $Path,
        "$Value`n",
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Test-OsrmToolInputs(
    [string]$Tool,
    [string]$ImageName,
    [string]$DataRoot,
    [string]$DatasetBaseName
) {
    $inputList = docker run --rm $ImageName $Tool --list-inputs 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    $requiredExtensions = @(
        $inputList |
            Where-Object { $_ -match '^required\s+' } |
            ForEach-Object { ($_ -split '\s+', 2)[1].Trim() }
    )
    if ($requiredExtensions.Count -eq 0) { return $false }
    foreach ($extension in $requiredExtensions) {
        $inputPath = Join-Path $DataRoot "$DatasetBaseName$extension"
        if (-not (Test-Path -LiteralPath $inputPath)) { return $false }
    }
    return $true
}

$workspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$resolvedData = [System.IO.Path]::GetFullPath((Join-Path $workspaceRoot $DataDirectory))
if (-not $resolvedData.StartsWith($workspaceRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OSRM data directory must stay inside the repository workspace."
}

docker info --format '{{.ServerVersion}}' | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker daemon is not available. Start Docker Desktop and retry."
}

Write-Output "Ensuring the pinned OSRM image is available..."
docker pull $Image | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Pinned OSRM image pull failed."
}

New-Item -ItemType Directory -Force -Path $resolvedData | Out-Null
$pbfPath = Join-Path $resolvedData "vietnam-latest.osm.pbf"
if (-not (Test-Path -LiteralPath $pbfPath)) {
    Write-Output "Downloading Vietnam OpenStreetMap PBF..."
    $downloadPath = "$pbfPath.download"
    curl.exe --fail --location --retry 3 --continue-at - --output $downloadPath $PbfUrl
    if ($LASTEXITCODE -ne 0) { throw "Vietnam PBF download failed." }
    Move-Item -LiteralPath $downloadPath -Destination $pbfPath -Force
}
if ((Get-Item -LiteralPath $pbfPath).Length -lt 1MB) {
    throw "Vietnam PBF is unexpectedly small; remove it and retry the download."
}

$sourcePbfHash = (Get-FileHash -LiteralPath $pbfPath -Algorithm SHA256).Hash.ToLowerInvariant()
$mount = "${resolvedData}:/data"

$routingPbfPath = Join-Path $resolvedData "vietnam-routing.osm.pbf"
$routingPbfTempPath = Join-Path $resolvedData "vietnam-routing.next.osm.pbf"
$routingSourceHashPath = Join-Path $resolvedData "vietnam-routing.source.sha256"
$routingFilterVersion = "osrm-v26.6.5-debian-car-speed-whitelist-v1"
$routingInputIdentity = "$sourcePbfHash|$routingFilterVersion"
$routingInputCurrent = (Test-Path -LiteralPath $routingPbfPath) -and
    (Test-Path -LiteralPath $routingSourceHashPath) -and
    ((Get-Content -LiteralPath $routingSourceHashPath -Raw).Trim() -eq $routingInputIdentity)
if (-not $routingInputCurrent) {
    Write-Output "Building a car-routing-only PBF with osmium..."
    docker build --tag $OsmiumImage --file "$workspaceRoot/docker/osmium/Dockerfile" $workspaceRoot
    if ($LASTEXITCODE -ne 0) { throw "osmium tool image build failed." }
    docker run --rm -t -v $mount $OsmiumImage tags-filter `
        /data/vietnam-latest.osm.pbf `
        w/highway=motorway,motorway_link,trunk,trunk_link,primary,primary_link,secondary,secondary_link,tertiary,tertiary_link,unclassified,residential,living_street,service,winter_road,ice_road `
        w/route=ferry,shuttle_train r/type=restriction r/route=ferry,shuttle_train `
        --output /data/vietnam-routing.next.osm.pbf --overwrite --fsync
    if ($LASTEXITCODE -ne 0) { throw "osmium routing PBF filter failed." }
    Move-Item -LiteralPath $routingPbfTempPath -Destination $routingPbfPath -Force
    Write-Utf8NoBom -Path $routingSourceHashPath -Value $routingInputIdentity
}
if ((Get-Item -LiteralPath $routingPbfPath).Length -lt 1MB) {
    throw "Filtered routing PBF is unexpectedly small."
}

$routingPbfHash = (Get-FileHash -LiteralPath $routingPbfPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($PrepareRoutingInputOnly) {
    Write-Output "OSRM_SOURCE_DATA_SHA256=$sourcePbfHash"
    Write-Output "OSRM_ROUTING_DATA_SHA256=$routingPbfHash"
    Write-Output "Routing input prepared; OSRM preprocessing was not started."
    return
}
$shortHash = $routingPbfHash.Substring(0, 12)
$imageVersion = ($Image -split ":")[-1].TrimStart("v")
$roadVersion = "osrm-$imageVersion-driving-vietnam-$shortHash"
$roadVersionPath = Join-Path $resolvedData "road-version.txt"
$datasetBaseName = "vietnam-routing"
$extractReady = Test-OsrmToolInputs `
    -Tool "osrm-partition" `
    -ImageName $Image `
    -DataRoot $resolvedData `
    -DatasetBaseName $datasetBaseName
$partitionReady = Test-OsrmToolInputs `
    -Tool "osrm-customize" `
    -ImageName $Image `
    -DataRoot $resolvedData `
    -DatasetBaseName $datasetBaseName
$routedReady = Test-OsrmToolInputs `
    -Tool "osrm-routed" `
    -ImageName $Image `
    -DataRoot $resolvedData `
    -DatasetBaseName $datasetBaseName
$requiredMldArtifacts = @(
    (Join-Path $resolvedData "$datasetBaseName.osrm.cells"),
    (Join-Path $resolvedData "$datasetBaseName.osrm.cell_metrics"),
    (Join-Path $resolvedData "$datasetBaseName.osrm.mldgr"),
    (Join-Path $resolvedData "$datasetBaseName.osrm.partition")
)
$routedReady = $routedReady -and (
    @($requiredMldArtifacts | Where-Object { -not (Test-Path -LiteralPath $_) }).Count -eq 0
)
$markerCurrent = (Test-Path -LiteralPath $roadVersionPath) -and
    ((Get-Content -LiteralPath $roadVersionPath -Raw).Trim() -eq $roadVersion)
$prepared = $routedReady -and $markerCurrent

if (-not $prepared) {
    if (-not $extractReady) {
        Write-Output "Running osrm-extract..."
        docker run --rm -t -v $mount $Image osrm-extract --threads $OsrmThreads -p /opt/car.lua /data/vietnam-routing.osm.pbf
        if ($LASTEXITCODE -ne 0) { throw "osrm-extract failed." }
    } else {
        Write-Output "osrm-extract outputs are complete; resuming."
    }
    if (-not $partitionReady) {
        Write-Output "Running osrm-partition..."
        docker run --rm -t -v $mount $Image osrm-partition /data/vietnam-routing.osrm
        if ($LASTEXITCODE -ne 0) { throw "osrm-partition failed." }
    } else {
        Write-Output "osrm-partition outputs are complete; resuming."
    }
    if (-not $routedReady) {
        Write-Output "Running osrm-customize..."
        docker run --rm -t -v $mount $Image osrm-customize /data/vietnam-routing.osrm
        if ($LASTEXITCODE -ne 0) { throw "osrm-customize failed." }
    } else {
        Write-Output "osrm-customize outputs are complete; validating."
    }
    docker run --rm -t -v $mount $Image osrm-routed `
        --algorithm mld --mmap --trial true /data/vietnam-routing.osrm
    if ($LASTEXITCODE -ne 0) { throw "OSRM routed trial validation failed." }
    Write-Utf8NoBom -Path $roadVersionPath -Value $roadVersion
} else {
    Write-Output "OSRM MLD dataset already matches the current PBF and image."
}

Write-Output "OSRM_SOURCE_DATA_SHA256=$sourcePbfHash"
Write-Output "OSRM_ROUTING_DATA_SHA256=$routingPbfHash"
Write-Output "STATION_GRAPH_ROAD_VERSION=$roadVersion"
Write-Output "road_version_file=$roadVersionPath"
Write-Output "Start service: docker compose --profile routing up -d osrm"
