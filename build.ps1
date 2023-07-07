pipenv requirements | Where-Object {$_ -ne ""} > src\requirements.txt
podman build . --tag eurobot
Remove-Item src\requirements.txt
