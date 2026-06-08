#!/usr/bin/env bash
#
# test_git_safe_branch.sh — verifies the #212 branch-ancestry guard.
#
# Builds throwaway local git repos in a temp dir (a fake "origin" + a working
# clone) and exercises scripts/git_safe_branch.sh against:
#
#   1. CLEAN  : a branch cut from a freshly-fetched origin/<default>  -> verify PASS
#   2. STALE  : a branch cut from an OLD base that misses a commit
#               later merged to origin, AND carries a foreign commit
#               (reproduces PR #210 contamination)                    -> verify FAIL
#   3. CREATE : `create` makes a branch whose tip == origin/<default> -> PASS
#
# No network, no Docker. Self-contained; safe to run anywhere.
#
# Exit 0 = all assertions held. Exit 1 = a regression.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GUARD="$SCRIPT_DIR/scripts/git_safe_branch.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

pass=0; fail=0
check() { # check <label> <expected_rc> <actual_rc>
    if [ "$2" = "$3" ]; then
        printf '  \033[32mPASS\033[0m %s (rc=%s)\n' "$1" "$3"; pass=$((pass+1))
    else
        printf '  \033[31mFAIL\033[0m %s (expected rc=%s, got rc=%s)\n' "$1" "$2" "$3"; fail=$((fail+1))
    fi
}

git_q() { git -c init.defaultBranch=master -c user.name=t -c user.email=t@t "$@"; }

# --- Build a bare "origin" with one commit on master ---------------------------
ORIGIN="$WORK/origin.git"
SEED="$WORK/seed"
git_q init -q "$SEED"
( cd "$SEED"
  echo "v1" > file.txt
  git_q add file.txt
  git_q commit -q -m "c1: initial"
)
git_q clone -q --bare "$SEED" "$ORIGIN" >/dev/null 2>&1

# --- Working clone, with origin/HEAD set so default-branch detection works ------
REPO="$WORK/repo"
git_q clone -q "$ORIGIN" "$REPO" >/dev/null 2>&1
git -C "$REPO" remote set-head origin --auto >/dev/null 2>&1

echo "== Scenario 1: CLEAN branch from fresh origin/master should PASS =="
# Someone merges a new commit to origin AFTER our clone (simulates PR #207 landing).
( cd "$SEED"
  echo "v2" > file.txt
  git_q commit -q -am "c2: merged PR (e.g. #207)"
)
# Publish c2 to the bare origin (so it's on origin/master after fetch).
git -C "$SEED" remote add origin "$ORIGIN" 2>/dev/null || true
git -C "$SEED" -c user.name=t -c user.email=t@t push -q origin master

# Use the guard's own create path: fetch + branch from fresh origin/master.
bash "$GUARD" create fix/clean-branch "$REPO" >/dev/null 2>&1
# It should contain c2 and verify clean.
bash "$GUARD" verify fix/clean-branch "$REPO" >/dev/null 2>&1
check "verify PASS on branch from fresh origin/master" 0 $?

echo "== Scenario 2: STALE/contaminated branch should FAIL =="
# Cut a branch from the OLD base (c1) — i.e. BEFORE c2 was merged — and add a
# foreign commit on top. This is exactly the PR #210 shape: missing a merged
# commit (c2) and carrying an unrelated commit.
C1=$(git -C "$REPO" rev-list --max-parents=0 origin/master | tail -1)
git -C "$REPO" checkout -q -b fix/stale-branch "$C1"
( cd "$REPO"
  echo "foreign" > other.txt
  git_q add other.txt
  git_q commit -q -m "foreign: another entity's in-flight commit (e.g. #208)"
)
bash "$GUARD" verify fix/stale-branch "$REPO" >/dev/null 2>&1
check "verify FAIL on branch cut from stale base (missing merged commit)" 1 $?

echo "== Scenario 3: create produces a clean-tipped branch =="
git -C "$REPO" checkout -q master 2>/dev/null || git -C "$REPO" checkout -q -B master origin/master
bash "$GUARD" create fix/created-clean "$REPO" >/dev/null 2>&1
created_tip=$(git -C "$REPO" rev-parse fix/created-clean)
origin_tip=$(git -C "$REPO" rev-parse origin/master)
[ "$created_tip" = "$origin_tip" ]; check "create: new branch tip == origin/master tip" 0 $?

echo
echo "----------------------------------------"
echo "Passed: $pass   Failed: $fail"
[ "$fail" -eq 0 ]
