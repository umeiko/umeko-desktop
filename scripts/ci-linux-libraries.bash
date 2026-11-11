#!/usr/bin/env bash
# Use Ubuntu's signed HTTPS archives instead of the runner's failing mirror list.
set -euo pipefail

if (( $# == 0 )); then
  echo 'Usage: bash scripts/ci-linux-libraries.bash PACKAGE...' >&2
  exit 2
fi
codename=$(lsb_release -cs)
if [[ ! $codename =~ ^[a-z]+$ ]]; then exit 2; fi
archive=https://archive.ubuntu.com/ubuntu
security=https://security.ubuntu.com/ubuntu
case $(dpkg --print-architecture) in
  amd64|i386) ;;
  *) archive=https://ports.ubuntu.com/ubuntu-ports; security=$archive ;;
esac
sources=$(mktemp)
dns_entries=$(mktemp)
hosts_patched=0
cleanup() {
  rm -f "$sources" "$dns_entries"
  if (( hosts_patched )); then
    sudo sed -i '/# umeko-ci-ubuntu-dns$/d' /etc/hosts
  fi
}
trap cleanup EXIT
archive_host=${archive#https://}
hosts=("${archive_host%%/*}")
if [[ $archive != "$security" ]]; then hosts+=(security.ubuntu.com); fi
python3 "$(dirname "$0")/ci-linux-dns.py" "${hosts[@]}" > "$dns_entries"
if [[ -s $dns_entries ]]; then
  hosts_patched=1
  sudo tee -a /etc/hosts < "$dns_entries" > /dev/null
fi
for suite in "$codename" "$codename-updates" "$codename-backports"; do
  printf 'deb %s %s main restricted universe multiverse\n' "$archive" "$suite"
done > "$sources"
printf 'deb %s %s-security main restricted universe multiverse\n' "$security" "$codename" >> "$sources"
options=(-o "Dir::Etc::sourcelist=$sources" -o 'Dir::Etc::sourceparts=-'
         -o 'Acquire::Retries=1' -o 'Acquire::http::Timeout=20'
         -o 'Acquire::https::Timeout=20' -o 'APT::Update::Error-Mode=any')
sudo apt-get "${options[@]}" update
sudo apt-get "${options[@]}" install -y "$@"
