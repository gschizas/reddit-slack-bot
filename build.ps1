pipenv requirements | Where-Object {$_ -ne ""} > src\requirements.txt
docker build . --tag eurobot
Remove-Item src\requirements.txt
