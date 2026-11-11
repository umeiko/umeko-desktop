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
trap 'rm -f "$sources"' EXIT
for suite in "$codename" "$codename-updates" "$codename-backports"; do
  printf 'deb %s %s main restricted universe multiverse\n' "$archive" "$suite"
done > "$sources"
printf 'deb %s %s-security main restricted universe multiverse\n' "$security" "$codename" >> "$sources"
options=(-o "Dir::Etc::sourcelist=$sources" -o 'Dir::Etc::sourceparts=-'
         -o 'Acquire::Retries=1' -o 'Acquire::http::Timeout=20'
         -o 'Acquire::https::Timeout=20' -o 'APT::Update::Error-Mode=any')
sudo apt-get "${options[@]}" update
sudo apt-get "${options[@]}" install -y "$@"
