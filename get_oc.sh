#!/usr/bin/env bash
curl https://api.github.com/repos/openshift/origin/releases/latest --output oc.json
oc_url=$(jq --raw-output '.assets[] | select(.name | contains("client-tools")) | select(.name | contains(".tar.gz")) | .browser_download_url' < oc.json)
oc_name=$(jq --raw-output '.assets[] | select(.name | contains("client-tools")) | select(.name | contains(".tar.gz")) | .name' < oc.json)
curl -L $oc_url --output $oc_name
tar xzf $oc_name
oc_folder=${oc_name%.tar.gz}
pushd $oc_folder
cp oc /usr/local/bin/
popd
rm -rf $oc_name
rm -rf $oc_folder