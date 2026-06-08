#!/usr/bin/env bash
#
# git_safe_branch.sh — safe work-branch creation + ancestry pre-flight guard.
#
# Fixes Issue #212: crew/orchestrator coder & github-workflow agents were
# branching from whatever was checked out (a stale local master, or another
# entity's in-flight branch) instead of a freshly-fetched origin/master. PR #210
# was cut from such a contaminated base — it MISSED a just-merged PR (#207) and
# PICKED UP another entity's commits (#208), so merging it would have reverted
# merged work and stolen those commits. Caught at self-pass by luck, not safeguard.
#
# This script makes the safe sequence executable + verifiable instead of prose:
#
#   create <branch> [repo_dir]
#       git fetch origin
#       git checkout -b <branch> origin/<default>      # fresh remote base, never local
#
#   verify [branch] [repo_dir]
#       Pre-flight guard. FAILS LOUDLY (exit 1) unless <branch> (default: HEAD)
#       is a clean descendant of the CURRENT origin/<default> — i.e. its
#       merge-base with origin/<default> equals origin/<default>'s tip.
#       This catches BOTH failure modes from #212:
#         - missing merged commits (stale base)  → merge-base is an ANCESTOR of tip
#         - foreign/divergent commits             → branch diverged before tip
#       Run this before committing or opening a PR; a contaminated ancestry is
#       then caught automatically, not by luck at human review.
#
# Default branch is detected from origin/HEAD (Awareness: master, Sextant: main),
# never assumed.
#
# Usage:
#   scripts/git_safe_branch.sh create fix/123-thing
#   scripts/git_safe_branch.sh create fix/123-thing /path/to/repo
#   scripts/git_safe_branch.sh verify                 # verify current HEAD
#   scripts/git_safe_branch.sh verify fix/123-thing
#   scripts/git_safe_branch.sh verify fix/123-thing /path/to/repo

set -euo pipefail

err()  { printf '\033[31m%s\033[0m\n' "$*" >&2; }   # red
ok()   { printf '\033[32m%s\033[0m\n' "$*" >&2; }   # green
info() { printf '%s\n' "$*" >&2; }

usage() {
    cat >&2 <<'EOF'
git_safe_branch.sh — safe branch creation + ancestry guard (Issue #212)

  create <branch> [repo_dir]   fetch origin, then branch from fresh origin/<default>
  verify [branch] [repo_dir]   fail loudly unless branch is a clean descendant of
                               current origin/<default> (run before commit/PR)
EOF
    exit 2
}

# Resolve the default branch name from the remote, e.g. "master" or "main".
default_branch() {
    local git=("$@")
    local ref
    # symbolic-ref is the reliable read; fall back to remote show if missing.
    if ref=$("${git[@]}" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null); then
        printf '%s\n' "${ref#origin/}"
        return 0
    fi
    ref=$("${git[@]}" remote show origin 2>/dev/null | sed -n 's/.*HEAD branch: //p' | head -1)
    if [ -n "$ref" ]; then
        printf '%s\n' "$ref"
        return 0
    fi
    err "Could not determine default branch from origin/HEAD."
    err "Fix: git remote set-head origin --auto"
    return 1
}

cmd_create() {
    local branch="${1:-}"
    local repo_dir="${2:-$(pwd)}"
    [ -n "$branch" ] || usage

    local git=(git -C "$repo_dir")
    "${git[@]}" rev-parse --show-toplevel >/dev/null 2>&1 || { err "Not a git repo: $repo_dir"; exit 1; }

    info "Fetching origin in $("${git[@]}" rev-parse --show-toplevel) ..."
    "${git[@]}" fetch origin

    local def; def=$(default_branch "${git[@]}")
    info "Branching '$branch' from fresh origin/$def ..."
    "${git[@]}" checkout -b "$branch" "origin/$def"

    # Confirm the new branch's tip IS origin/<default>'s tip (clean cut).
    local head remote_tip
    head=$("${git[@]}" rev-parse HEAD)
    remote_tip=$("${git[@]}" rev-parse "origin/$def")
    if [ "$head" != "$remote_tip" ]; then
        err "POST-CREATE CHECK FAILED: new branch tip ($head) != origin/$def tip ($remote_tip)."
        exit 1
    fi
    ok "OK: '$branch' created from origin/$def @ ${remote_tip:0:12} (clean base)."
}

cmd_verify() {
    local repo_dir branch
    # Args: [branch] [repo_dir]. Both optional and order-flexible-ish:
    # if first arg is an existing dir, treat it as repo_dir.
    if [ $# -ge 1 ] && [ -d "${1:-}" ]; then
        repo_dir="$1"; branch=""
    else
        branch="${1:-}"
        repo_dir="${2:-$(pwd)}"
    fi

    local git=(git -C "$repo_dir")
    "${git[@]}" rev-parse --show-toplevel >/dev/null 2>&1 || { err "Not a git repo: $repo_dir"; exit 1; }

    [ -n "$branch" ] || branch=$("${git[@]}" rev-parse --abbrev-ref HEAD)

    info "Fetching origin to compare against the LIVE remote tip ..."
    "${git[@]}" fetch origin

    local def; def=$(default_branch "${git[@]}")
    local remote_tip branch_tip mergebase
    remote_tip=$("${git[@]}" rev-parse "origin/$def")
    branch_tip=$("${git[@]}" rev-parse "$branch")
    mergebase=$("${git[@]}" merge-base "$branch" "origin/$def")

    info "branch      : $branch @ ${branch_tip:0:12}"
    info "origin/$def : ${remote_tip:0:12}"
    info "merge-base  : ${mergebase:0:12}"

    # CLEAN iff the branch already contains every commit on origin/<default>,
    # i.e. merge-base(branch, origin/<default>) == origin/<default> tip.
    # If not, the branch was cut from a stale/contaminated base: it is missing
    # merged commits (and/or diverged onto foreign commits). FAIL LOUDLY.
    if [ "$mergebase" = "$remote_tip" ]; then
        ok "PASS: '$branch' is a clean descendant of current origin/$def (no contaminated ancestry)."
        return 0
    fi

    err "============================================================"
    err "FAIL (#212 guard): '$branch' is NOT based on current origin/$def."
    err ""
    err "  Its merge-base with origin/$def is ${mergebase:0:12},"
    err "  but origin/$def is now at        ${remote_tip:0:12}."
    err ""
    local behind
    behind=$("${git[@]}" rev-list --count "$branch".."origin/$def" 2>/dev/null || echo '?')
    err "  This branch is missing $behind commit(s) that are on origin/$def."
    err "  Merging it could REVERT merged work and/or carry foreign commits."
    err ""
    err "  Remedy: cherry-pick your real change onto a fresh branch:"
    err "    scripts/git_safe_branch.sh create <new-branch> $repo_dir"
    err "    git -C $repo_dir cherry-pick <your-commit(s)>"
    err "============================================================"
    return 1
}

main() {
    local sub="${1:-}"
    shift || true
    case "$sub" in
        create) cmd_create "$@" ;;
        verify) cmd_verify "$@" ;;
        ""|-h|--help|help) usage ;;
        *) err "Unknown subcommand: $sub"; usage ;;
    esac
}

main "$@"
