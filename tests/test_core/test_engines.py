"""
Tests for newly extracted OOP Core Engines:
- ChangeClassifier (src/core/classifier.py)
- UpstreamResolver (src/core/upstream.py)
- ForwardEngine (src/core/forwarder.py)
- OrphanEngine (src/core/orphan.py)
- ProjectRegistry (src/core/project.py)
"""

import pytest
from src.core import (
    ChangeClassifier,
    UpstreamResolver,
    ForwardEngine,
    OrphanEngine,
    ProjectRegistry,
)
from src.schema.models import ForwardRule, UpstreamEntry, MemoryEntry, ProjectCreate


class TestChangeClassifierCore:
    def test_classifier_matches_upstream_and_manual(self):
        upstreams = [UpstreamEntry(name="anthropic", path=".data/.anthropics-skills")]
        forwards = [ForwardRule(**{"from": ".data/.anthropics-skills/skills", "to": "skills/storage/anthropic", "enabled": True})]
        classifier = ChangeClassifier(forwards, upstreams, repo_root="")

        status_text = ' M "skills/storage/anthropic/test.md"\n?? custom/tool.py'
        up_changes, manual = classifier.classify_status(status_text)

        assert "anthropic" in up_changes
        assert "skills/storage/anthropic/test.md" in up_changes["anthropic"]
        assert "custom/tool.py" in manual

    def test_filter_staged_deletions(self):
        status_text = 'D  deleted.txt\n M modified.txt'
        files = ["deleted.txt", "modified.txt"]
        kept = ChangeClassifier.filter_staged_deletions(files, status_text)
        assert kept == ["modified.txt"]


class TestUpstreamResolverCore:
    def test_resolve_sparse_subpaths(self):
        entry = UpstreamEntry(name="ui-ux", path=".data/.ui-ux")
        forwards = [
            ForwardRule(**{"from": ".data/.ui-ux/skills/theme", "to": "skills/theme", "enabled": True}),
            ForwardRule(**{"from": ".data/.ui-ux/skills/icons", "to": "skills/icons", "enabled": True}),
        ]
        subpaths = UpstreamResolver.resolve_sparse_subpaths(entry, forwards)
        assert subpaths == ["skills/icons", "skills/theme"]


class TestOrphanEngineCore:
    def test_detect_orphans_on_rule_change(self):
        engine = OrphanEngine(repo_root="")
        prev = [
            MemoryEntry(forward_id="f1", upstream_id="u1", to_path="skills/storage/old_name"),
        ]
        curr = [
            ForwardRule(forward_id="f1", upstream_id="u1", to_path="skills/storage/new_name", enabled=True),
        ]
        upstreams = [UpstreamEntry(upstream_id="u1", name="test")]

        orphans = engine.detect_orphans(previous=prev, current=curr, upstreams=upstreams)
        assert "skills/storage/old_name" in orphans


class TestForwardEngineCore:
    def test_memory_entry_creation(self):
        engine = ForwardEngine(repo_root="/repo")
        rule = ForwardRule(
            upstream_id="u123",
            forward_id="f123",
            project_name="my_proj",
            from_path="/repo/.data/.proj/skills",
            to_path="/repo/skills/storage/proj",
        )
        entry = engine.create_memory_entry(rule)
        assert entry.upstream_id == "u123"
        assert entry.forward_id == "f123"
        assert entry.from_path == ".data/.proj/skills"
        assert entry.to_path == "skills/storage/proj"
