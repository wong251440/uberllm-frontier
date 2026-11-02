#!/usr/bin/env bash
# One-time GitHub Pages deploy helper. Requires git + authenticated GitHub CLI.
# This script creates one NEW PUBLIC repository and enables Pages. Review before running.
set -euo pipefail

cd "$(dirname "$0")/.."
echo 'WARNING: Artificial Analysis Free API/index data is internal-use only;'
echo 'publishing the included Intelligence Index data to public GitHub Pages needs redistribution rights.'
if [[ "${CONFIRM_PUBLIC_AA_DATA:-}" != 'yes' ]]; then
  read -r -p 'Do you have permission to publish this score dataset? Type yes to continue: ' ANSWER
  if [[ "$ANSWER" != 'yes' ]]; then
    echo 'Stopped before making any change to your GitHub account.'
    exit 1
  fi
fi
REPO_NAME="${1:-uberllm-frontier}"
if ! command -v gh >/dev/null 2>&1; then
  echo 'Please install GitHub CLI (gh) from https://cli.github.com/ first.' >&2
  exit 1
fi
if ! command -v git >/dev/null 2>&1; then
  echo 'Please install Git first.' >&2
  exit 1
fi
gh auth status >/dev/null
OWNER="$(gh api user --jq .login)"
if [[ ! "$REPO_NAME" =~ ^[a-zA-Z0-9._-]+$ ]]; then
  echo 'Repository name must contain only letters, numbers, dashes, periods, underscores.' >&2
  exit 1
fi
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo 'Existing Git repository found; will not overwrite its remote or branch.' >&2
  echo 'Use the manual instructions in README.md instead.' >&2
  exit 1
fi
git init
git branch -M main
git add .
git -c user.name="${OWNER}" -c user.email="${OWNER}@users.noreply.github.com" commit -m "Launch Frontier Atlas dashboard"
echo "Creating public GitHub repo ${OWNER}/${REPO_NAME}..."
gh repo create "${OWNER}/${REPO_NAME}" --public --source . --remote origin --push
# API POST can take a moment after repository creation; if it fails, use Settings > Pages.
if gh api --method POST "repos/${OWNER}/${REPO_NAME}/pages" \
    -f 'build_type=workflow' >/dev/null; then
  echo 'GitHub Pages enabled.'
else
  echo 'Could not enable Pages through API. Go to Settings > Pages > Source: GitHub Actions.'
fi
if gh workflow run daily-update.yml --ref main >/dev/null; then
  echo 'Triggered the first data refresh and Pages deployment.'
else
  echo 'GitHub has not recognized the workflow yet; open Actions > Daily UberLLM tracking + GitHub Pages publish > Run workflow.'
fi
echo "Your site, once published: https://${OWNER}.github.io/${REPO_NAME}/"
echo 'IMPORTANT: Verify Artificial Analysis redistribution permission BEFORE enabling public Pages.'
