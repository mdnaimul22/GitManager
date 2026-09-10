"""
Unit and integration tests for Structured Memory & Auto-Prune Mirror.

Verifies:
1. Structured memory CRUD (memory_id, upstream_id, forward_id, lineage).
2. Auto-Prune Mirror: Extraneous files and .git folders are pruned from dst.
3. from_path change detection: Cleans up old source files when user fixes 'from' path.
4. Single rule deletion out of multiple rules: Only the deleted rule's destination is purged.
5. Upstream deletion: Cascades to remove all destinations associated with that upstream.
6. to_path rename: Cleans up old destination when destination is changed.
"""

import os
import pytest
from src.config import exists, is_file, is_dir, read_json, write_json, Settings
from src.schema.models import ForwardRule, MemoryEntry, UpstreamEntry
from src.services.forward import (
    ForwardService,
    load_memory,
    save_memory,
)


class TestStructuredMemoryAndAutoPrune:
    """Tests for structured memory registry and auto-prune mirroring."""

    def test_load_and_save_structured_memory(self, tmp_path):
        mem_file = f"{tmp_path}/memory.json"

        entries = [
            MemoryEntry(
                upstream_id="up-1",
                forward_id="fwd-1",
                project_name="proj-1",
                from_path=".data/p1/skills",
                to_path="skills/storage/p1",
                last_synced="2026-09-08T00:00:00",
            ),
            MemoryEntry(
                upstream_id="up-2",
                forward_id="fwd-2",
                project_name="proj-2",
                from_path=".data/p2/skills",
                to_path="skills/storage/p2",
                last_synced="2026-09-08T00:00:00",
            ),
        ]

        save_memory(entries, mem_file)
        assert exists(mem_file)

        loaded = load_memory(mem_file)
        assert len(loaded) == 2
        assert loaded[0].upstream_id == "up-1"
        assert loaded[0].forward_id == "fwd-1"
        assert len(loaded[0].memory_id) == 8
        assert loaded[0].from_path == ".data/p1/skills"
        assert loaded[0].to_path == "skills/storage/p1"

        # Test legacy format conversion
        legacy_file = f"{tmp_path}/legacy_memory.json"
        write_json(legacy_file, ["skills/storage/legacy_a", "skills/storage/legacy_b"])
        legacy_loaded = load_memory(legacy_file)
        assert len(legacy_loaded) == 2
        assert legacy_loaded[0].to_path == "skills/storage/legacy_a"

    def test_auto_prune_mirror_removes_extraneous_files_and_git(self, tmp_path):
        """Auto-Prune Mirror removes non-matching files and .git from destination."""
        src_dir = tmp_path / "src_skills"
        src_dir.mkdir()
        (src_dir / "valid_skill").mkdir()
        (src_dir / "valid_skill" / "SKILL.md").write_text("valid content")

        dst_dir = tmp_path / "dst_skills"
        dst_dir.mkdir()
        # Create stray files in dst that are NOT in src (e.g. from a mistaken previous copy)
        (dst_dir / "ADOPTERS.md").write_text("old junk")
        (dst_dir / "package.json").write_text("{}")
        (dst_dir / ".git").mkdir()
        (dst_dir / ".git" / "HEAD").write_text("ref: refs/heads/main")
        (dst_dir / "stray_dir").mkdir()
        (dst_dir / "stray_dir" / "junk.txt").write_text("junk")

        rule = ForwardRule(
            from_path=str(src_dir),
            to_path=str(dst_dir),
            enabled=True,
        )

        copied, memory = ForwardService().forward([rule])
        assert len(copied) == 1

        # Destination must contain valid_skill
        assert (dst_dir / "valid_skill" / "SKILL.md").exists()

        # Destination must NOT contain the stray files or .git!
        assert not (dst_dir / "ADOPTERS.md").exists()
        assert not (dst_dir / "package.json").exists()
        assert not (dst_dir / ".git").exists()
        assert not (dst_dir / "stray_dir").exists()

    def test_from_path_change_cleans_up_old_source_files(self, tmp_path):
        """
        Simulates the user's exact case:
        Run 1: 'from' pointed to repo root by mistake.
        Run 2: user fixed 'from' to repo_root/skills.
        The old root files in dst must be cleaned up automatically!
        """
        repo_root = tmp_path / "upstream_repo"
        repo_root.mkdir()
        (repo_root / "ADOPTERS.md").write_text("root file")
        (repo_root / "bun.lock").write_text("lock file")
        (repo_root / "skills").mkdir()
        (repo_root / "skills" / "my_skill").mkdir()
        (repo_root / "skills" / "my_skill" / "SKILL.md").write_text("skill")

        dst_dir = tmp_path / "storage" / "heygen"

        # ── RUN 1: Mistaken from_path (repo root)
        rule_v1 = ForwardRule(
            upstream_id="up-heygen",
            forward_id="fwd-heygen",
            from_path=str(repo_root),
            to_path=str(dst_dir),
            enabled=True,
        )
        _, mem_v1 = ForwardService().forward([rule_v1])
        assert (dst_dir / "ADOPTERS.md").exists()
        assert (dst_dir / "bun.lock").exists()

        # ── RUN 2: User fixes from_path to repo_root/skills
        rule_v2 = ForwardRule(
            upstream_id="up-heygen",
            forward_id="fwd-heygen",
            from_path=str(repo_root / "skills"),
            to_path=str(dst_dir),
            enabled=True,
        )

        # Cleanup orphans detects from_path changed and purges dst
        removed = ForwardService().cleanup_orphans(previous=mem_v1, current=[rule_v2])
        assert len(removed) >= 1

        # Now ForwardService mirrors new source
        _, mem_v2 = ForwardService().forward([rule_v2])

        # VERIFY: my_skill exists directly in dst
        assert (dst_dir / "my_skill" / "SKILL.md").exists()
        # VERIFY: old repo root junk is GONE!
        assert not (dst_dir / "ADOPTERS.md").exists()
        assert not (dst_dir / "bun.lock").exists()

    def test_single_rule_deleted_from_multi_rule_upstream(self, tmp_path):
        """Deleting 1 rule out of 3 under an upstream purges only that destination."""
        d1 = tmp_path / "dst1"
        d2 = tmp_path / "dst2"
        d3 = tmp_path / "dst3"
        for d in (d1, d2, d3):
            d.mkdir(parents=True)
            (d / "test.txt").write_text("content")

        up = UpstreamEntry(upstream_id="up-x", project_name="X")
        f1 = ForwardRule(forward_id="f1", upstream_id="up-x", to_path=str(d1))
        f2 = ForwardRule(forward_id="f2", upstream_id="up-x", to_path=str(d2))
        f3 = ForwardRule(forward_id="f3", upstream_id="up-x", to_path=str(d3))

        mem_entries = [
            MemoryEntry(upstream_id="up-x", forward_id="f1", to_path=str(d1)),
            MemoryEntry(upstream_id="up-x", forward_id="f2", to_path=str(d2)),
            MemoryEntry(upstream_id="up-x", forward_id="f3", to_path=str(d3)),
        ]

        # Action: delete f2 (submit only f1 and f3)
        removed = ForwardService().cleanup_orphans(
            previous=mem_entries,
            current=[f1, f3],
            upstreams=[up],
        )

        assert "dst2" in removed
        assert not d2.exists()  # d2 was removed!
        assert d1.exists()      # d1 is untouched
        assert d3.exists()      # d3 is untouched

    def test_entire_upstream_deleted_cascades_to_all_its_rules(self, tmp_path):
        """Deleting an upstream removes all destination folders associated with it."""
        d_a1 = tmp_path / "dst_a1"
        d_a2 = tmp_path / "dst_a2"
        d_b1 = tmp_path / "dst_b1"
        for d in (d_a1, d_a2, d_b1):
            d.mkdir(parents=True)
            (d / "file.txt").write_text("data")

        up_a = UpstreamEntry(upstream_id="up-A", project_name="A")
        up_b = UpstreamEntry(upstream_id="up-B", project_name="B")

        mem_entries = [
            MemoryEntry(upstream_id="up-A", forward_id="fa1", to_path=str(d_a1)),
            MemoryEntry(upstream_id="up-A", forward_id="fa2", to_path=str(d_a2)),
            MemoryEntry(upstream_id="up-B", forward_id="fb1", to_path=str(d_b1)),
        ]

        # Action: Delete upstream A entirely (submit only up_b and its forward)
        f_b1 = ForwardRule(forward_id="fb1", upstream_id="up-B", to_path=str(d_b1))
        removed = ForwardService().cleanup_orphans(
            previous=mem_entries,
            current=[f_b1],
            upstreams=[up_b],
        )

        assert "dst_a1" in removed
        assert "dst_a2" in removed
        assert not d_a1.exists()
        assert not d_a2.exists()
        # B is untouched
        assert d_b1.exists()

    def test_to_path_renamed_cleans_old_destination(self, tmp_path):
        """When to_path is changed for a rule, old to_path is removed."""
        old_dst = tmp_path / "old_dest"
        old_dst.mkdir()
        (old_dst / "old.txt").write_text("old")

        new_dst = tmp_path / "new_dest"

        rule = ForwardRule(forward_id="fwd-rename", upstream_id="up-1", to_path=str(new_dst))
        mem_entry = MemoryEntry(forward_id="fwd-rename", upstream_id="up-1", to_path=str(old_dst))

        removed = ForwardService().cleanup_orphans(
            previous=[mem_entry],
            current=[rule],
            upstreams=[UpstreamEntry(upstream_id="up-1")],
        )

        assert "old_dest" in removed
        assert not old_dst.exists()
