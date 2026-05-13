"""Tests for Issue #226: per-entity cwd identity isolation.

Verifies the architecture invariants that prevent cross-entity bleed:
- Each entity has its own CLAUDE.md in its entity directory
- No shared `.claude/CLAUDE.md` symlink at project root (the old bleed corridor)
- The CC cwd-ancestor walk from an entity directory finds both project and
  entity CLAUDE.md
- `start-entity.sh` cd's into the entity directory before exec
- Concurrent invocations don't race on shared filesystem state

The bleed scenario this prevents (from issue #226):
    # Terminal A: ./scripts/start-entity.sh lyra
    # Terminal B (concurrent): ./scripts/start-entity.sh caia
    # Old architecture: terminal A's `.claude/CLAUDE.md` symlink gets clobbered
    # to Caia's identity, so when terminal A compacts and re-reads CLAUDE.md
    # from disk, it loads Caia's identity inside a Lyra session.
"""

import os
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENTITIES_DIR = PROJECT_ROOT / "entities"
START_ENTITY_SH = PROJECT_ROOT / "scripts" / "start-entity.sh"


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------


def test_template_has_claude_md():
    """The committed template documents the architecture via its own structure."""
    template_readme = ENTITIES_DIR / "_template" / "README.md"
    assert template_readme.exists()
    contents = template_readme.read_text()
    # README must describe the new architecture, not the old symlink one
    assert "CLAUDE.md" in contents
    assert "cwd" in contents.lower()
    # The old "symlinked to `.claude/CLAUDE.md`" prescription must be gone
    assert "is symlinked to `.claude/CLAUDE.md` on startup" not in contents


def test_project_root_has_claude_md():
    """The shared project CLAUDE.md (loaded first, lower attention) exists."""
    assert (PROJECT_ROOT / "CLAUDE.md").is_file()


def test_no_shared_claude_md_symlink():
    """The `.claude/CLAUDE.md` bleed corridor must not exist.

    The pre-#226 architecture symlinked `.claude/CLAUDE.md` to the active
    entity's identity file. Two concurrent entity starts would race on this
    shared path. The fix removes the symlink entirely and uses per-entity
    cwd instead.
    """
    shared = PROJECT_ROOT / ".claude" / "CLAUDE.md"
    assert not shared.exists(), (
        f"{shared} should not exist post-#226 — its presence indicates the "
        "shared-symlink bleed corridor has been re-introduced. Identity now "
        "lives in entities/<entity>/CLAUDE.md and loads via the cwd-ancestor "
        "walk when start-entity.sh cd's into the entity directory."
    )
    # Also catch dangling symlinks (lexists vs exists)
    assert not shared.is_symlink(), (
        f"{shared} is a symlink — even dangling, this is the old bleed "
        "corridor. Delete it."
    )


@pytest.mark.parametrize("entity", ["lyra", "caia"])
def test_entity_has_claude_md(entity):
    """Each runtime entity has its own CLAUDE.md.

    Skips if the entity hasn't been initialized locally (gitignored — each
    developer may have a different set of entities checked out).
    """
    entity_dir = ENTITIES_DIR / entity
    if not entity_dir.is_dir():
        pytest.skip(f"Entity {entity} not present in this checkout")
    claude_md = entity_dir / "CLAUDE.md"
    assert claude_md.is_file(), (
        f"{claude_md} missing — entity won't have compaction-safe identity "
        f"grounding. start-entity.sh warns about this but still launches."
    )
    # Sanity: file is non-trivial (real identity content, not a stub)
    assert claude_md.stat().st_size > 500


@pytest.mark.parametrize("entity", ["lyra", "caia"])
def test_no_orphan_claude_identity_md(entity):
    """The renamed-away `claude_identity.md` should not still be present.

    A leftover would mean the runtime rename didn't happen and the entity
    is still depending on the old filename — start-entity.sh would warn
    about missing CLAUDE.md while the old file sits next to it.
    """
    entity_dir = ENTITIES_DIR / entity
    if not entity_dir.is_dir():
        pytest.skip(f"Entity {entity} not present in this checkout")
    legacy = entity_dir / "claude_identity.md"
    assert not legacy.exists(), (
        f"{legacy} still exists alongside CLAUDE.md — the rename to "
        f"CLAUDE.md is incomplete. Remove the old file."
    )


# ---------------------------------------------------------------------------
# CC cwd-ancestor walk simulation
# ---------------------------------------------------------------------------


def _walk_claude_md_ancestors(start: Path, stop_at: Path) -> list[Path]:
    """Mimic CC's CLAUDE.md walk: from `start`, climb to `stop_at`, returning
    every `CLAUDE.md` found along the way.

    Result is ordered cwd-first (closest); CC's actual concat order is the
    reverse (most distant first, so cwd appears last in the prompt with
    highest model attention).
    """
    found = []
    cur = start.resolve()
    stop = stop_at.resolve()
    while True:
        candidate = cur / "CLAUDE.md"
        if candidate.is_file():
            found.append(candidate)
        if cur == stop:
            break
        parent = cur.parent
        if parent == cur:  # reached filesystem root
            break
        cur = parent
    return found


@pytest.mark.parametrize("entity", ["lyra", "caia"])
def test_walk_finds_both_claude_md(entity):
    """From an entity directory, CC's walk should find project + entity CLAUDE.md.

    This is the core architecture: the entity directory IS the cwd, the walk
    climbs to the project root, and both CLAUDE.md files end up in the
    concatenated identity context.
    """
    entity_dir = ENTITIES_DIR / entity
    if not entity_dir.is_dir():
        pytest.skip(f"Entity {entity} not present in this checkout")

    found = _walk_claude_md_ancestors(entity_dir, PROJECT_ROOT)
    paths = [p.resolve() for p in found]

    project_claude = (PROJECT_ROOT / "CLAUDE.md").resolve()
    entity_claude = (entity_dir / "CLAUDE.md").resolve()

    assert entity_claude in paths, (
        f"Entity CLAUDE.md {entity_claude} not picked up by the walk"
    )
    assert project_claude in paths, (
        f"Project CLAUDE.md {project_claude} not picked up by the walk"
    )


@pytest.mark.parametrize("entity", ["lyra", "caia"])
def test_walk_order_gives_entity_highest_attention(entity):
    """CC concatenates most-distant-first; cwd is last (highest attention).

    The walk function returns cwd-first; reversing it gives the actual concat
    order. The entity's CLAUDE.md must be at the END of that order — that's
    where the model puts the most attention.
    """
    entity_dir = ENTITIES_DIR / entity
    if not entity_dir.is_dir():
        pytest.skip(f"Entity {entity} not present in this checkout")

    found = _walk_claude_md_ancestors(entity_dir, PROJECT_ROOT)
    concat_order = list(reversed(found))  # most-distant first
    assert concat_order[-1].resolve() == (entity_dir / "CLAUDE.md").resolve()


# ---------------------------------------------------------------------------
# start-entity.sh behavior
# ---------------------------------------------------------------------------


def test_start_script_exists_and_executable():
    assert START_ENTITY_SH.is_file()
    assert os.access(START_ENTITY_SH, os.X_OK)


def test_start_script_does_not_create_symlink():
    """start-entity.sh must no longer touch `.claude/CLAUDE.md`.

    Grep the script source for the old symlink dance. The text 'ln -s' on
    `.claude/CLAUDE.md` was the bleed corridor.
    """
    src = START_ENTITY_SH.read_text()
    # The literal symlink-creating commands must be gone
    assert "ln -s" not in src or ".claude/CLAUDE.md" not in src.replace("ln -s", "ln_s_marker"), (
        "start-entity.sh still has a `ln -s` creating `.claude/CLAUDE.md` — "
        "the bleed corridor has been re-introduced."
    )
    # And the legacy `claude_identity.md` filename ref should be gone
    assert "claude_identity.md" not in src, (
        "start-entity.sh still references the legacy `claude_identity.md` "
        "filename. The runtime kernel is now `CLAUDE.md`."
    )


def test_start_script_cds_into_entity_dir():
    """start-entity.sh must cd into the entity directory before exec.

    This is the structural source of isolation: CC's cwd-ancestor walk only
    finds the right entity CLAUDE.md if it starts from the entity directory.
    """
    src = START_ENTITY_SH.read_text()
    assert 'cd "$ENTITY_PATH"' in src or "cd $ENTITY_PATH" in src, (
        "start-entity.sh must `cd \"$ENTITY_PATH\"` before exec'ing claude."
    )
    # And the cd must come before the exec
    cd_idx = src.find('cd "$ENTITY_PATH"')
    exec_idx = src.find("exec ")
    assert cd_idx != -1 and exec_idx != -1 and cd_idx < exec_idx, (
        "The cd must precede the exec — otherwise CC inherits the wrong cwd."
    )


def test_start_script_dry_run_with_mocked_claude(tmp_path):
    """Exercise start-entity.sh end-to-end with a fake claude binary.

    The fake records its cwd and ENTITY_NAME/ENTITY_PATH env to a file.
    We then assert the cwd was the entity dir and the env vars were set.
    """
    # Create a fake CLAUDE_BIN that records what it sees
    fake_claude_dir = tmp_path / "fakebin"
    fake_claude_dir.mkdir()
    fake_claude = fake_claude_dir / "claude"
    record_file = tmp_path / "record.txt"
    fake_claude.write_text(
        f"#!/bin/bash\n"
        f"echo \"cwd=$(pwd)\" >> {record_file}\n"
        f"echo \"ENTITY_NAME=$ENTITY_NAME\" >> {record_file}\n"
        f"echo \"ENTITY_PATH=$ENTITY_PATH\" >> {record_file}\n"
        f"echo \"args=$*\" >> {record_file}\n"
        f"exit 0\n"
    )
    fake_claude.chmod(0o755)

    # Run for each available entity
    for entity in ("lyra", "caia"):
        entity_dir = ENTITIES_DIR / entity
        if not entity_dir.is_dir():
            continue
        record_file.unlink(missing_ok=True)

        # Override CLAUDE_BIN by manipulating PATH; start-entity.sh prefers
        # ~/.claude/local/claude but falls back to PATH `claude`.
        # The fallback path makes the test work even when the managed install
        # exists, by pointing HOME at an empty temp dir.
        env = os.environ.copy()
        env["HOME"] = str(tmp_path / "fake_home")
        (tmp_path / "fake_home").mkdir(exist_ok=True)
        env["PATH"] = f"{fake_claude_dir}:{env.get('PATH', '')}"

        result = subprocess.run(
            [str(START_ENTITY_SH), entity, "--test-arg"],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"start-entity.sh {entity} failed: stderr={result.stderr}"
        )
        recorded = record_file.read_text()
        assert f"ENTITY_NAME={entity}" in recorded
        assert f"ENTITY_PATH={entity_dir}" in recorded
        assert f"cwd={entity_dir}" in recorded
        # start-entity.sh prepends --dangerously-skip-permissions, then user args
        assert "--test-arg" in recorded
        assert "--dangerously-skip-permissions" in recorded

        # And — the bleed-corridor check: no symlink was created as a side effect
        shared = PROJECT_ROOT / ".claude" / "CLAUDE.md"
        assert not shared.exists() and not shared.is_symlink(), (
            f"start-entity.sh created or restored {shared} — the bleed corridor "
            "is back."
        )


# ---------------------------------------------------------------------------
# Concurrent invocation: no shared-file race
# ---------------------------------------------------------------------------


def test_concurrent_starts_dont_race_on_shared_file(tmp_path):
    """Two concurrent start-entity.sh invocations (lyra + caia) must not race.

    Pre-#226: both invocations clobbered `.claude/CLAUDE.md`, last writer wins.
    Post-#226: there is no shared write target, so concurrency is structurally
    safe.

    The test starts both processes in parallel and verifies:
      - Both succeed
      - Each fake-claude saw its own entity's cwd / env
      - No `.claude/CLAUDE.md` artifact appears
    """
    if not (ENTITIES_DIR / "lyra").is_dir() or not (ENTITIES_DIR / "caia").is_dir():
        pytest.skip("Both lyra and caia entities required for this test")

    fake_claude_dir = tmp_path / "fakebin"
    fake_claude_dir.mkdir()
    fake_claude = fake_claude_dir / "claude"
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    # Fake sleeps briefly so the two processes overlap in time
    fake_claude.write_text(
        "#!/bin/bash\n"
        f"out={record_dir}/${{ENTITY_NAME}}.txt\n"
        "echo \"cwd=$(pwd)\" > $out\n"
        "echo \"ENTITY_NAME=$ENTITY_NAME\" >> $out\n"
        "echo \"ENTITY_PATH=$ENTITY_PATH\" >> $out\n"
        "sleep 0.5\n"  # ensure overlap
        "exit 0\n"
    )
    fake_claude.chmod(0o755)

    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "fake_home")
    (tmp_path / "fake_home").mkdir(exist_ok=True)
    env["PATH"] = f"{fake_claude_dir}:{env.get('PATH', '')}"

    p1 = subprocess.Popen(
        [str(START_ENTITY_SH), "lyra"],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    p2 = subprocess.Popen(
        [str(START_ENTITY_SH), "caia"],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    r1 = p1.wait(timeout=10)
    r2 = p2.wait(timeout=10)
    assert r1 == 0 and r2 == 0

    lyra_rec = (record_dir / "lyra.txt").read_text()
    caia_rec = (record_dir / "caia.txt").read_text()
    assert "ENTITY_NAME=lyra" in lyra_rec
    assert f"cwd={ENTITIES_DIR / 'lyra'}" in lyra_rec
    assert "ENTITY_NAME=caia" in caia_rec
    assert f"cwd={ENTITIES_DIR / 'caia'}" in caia_rec

    # And the bleed-corridor check after concurrent runs
    shared = PROJECT_ROOT / ".claude" / "CLAUDE.md"
    assert not shared.exists() and not shared.is_symlink()
