param(
    [Parameter(Mandatory=$true)]
    [string]
    $EnvironmentFile
)

docker run -it `
    -v "$((Get-Item .refreshtoken).FullName):/app/.refreshtoken" `
    -v "$((Get-Item config).FullName):/app/config" `
    -v "$((Get-Item data).FullName):/app/data" `
    -v "$((Get-Item logs).FullName):/app/logs" `
    --env-file $EnvironmentFile `
    eurobot