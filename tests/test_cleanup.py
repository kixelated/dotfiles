import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "cleanup", Path(__file__).parents[1] / "bin/clean-worktrees.py"
)
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


class CleanupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "main"
        self.wt = self.root / "linked [test]"
        self.repo.mkdir()
        self.git(self.repo, "init", "-q")
        self.git(self.repo, "config", "user.name", "Test")
        self.git(self.repo, "config", "user.email", "test@example.com")
        (self.repo / "source").write_text("source")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-qm", "init")
        self.git(self.repo, "worktree", "add", "-q", "--detach", str(self.wt))
        self.addCleanup(patch.stopall)
        patch.object(cleanup, "processes", return_value=[]).start()
        patch.object(cleanup, "builders_idle").start()
        patch.object(cleanup, "workspace_targets", return_value={}).start()
        patch.object(cleanup, "merged_pull_requests", return_value=[]).start()
        patch.dict(os.environ, {"XDG_STATE_HOME": str(self.root / "state")}).start()
        self.executed = []
        original = cleanup.execute

        def execute(args, dry):
            self.executed.append(list(map(str, args)))
            if args[0] != "mbx":
                original(args, dry)

        patch.object(cleanup, "execute", side_effect=execute).start()

    def git(self, root, *args):
        return subprocess.check_output(
            ["git", "-C", str(root), *args], stderr=subprocess.PIPE
        )

    def entry(self):
        return list(cleanup.worktrees(self.repo))[1]

    def retire(self, dry=False, archive=False):
        cleanup.retire(self.repo, self.entry(), dry, archive)

    def ignored(self, pattern, path, content="local"):
        self.git(self.wt, "config", "core.excludesFile", str(self.root / "ignore"))
        (self.root / "ignore").write_text(pattern + "\n")
        target = self.wt / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target

    def feature(self, base="main"):
        initial = self.git(self.repo, "rev-parse", "HEAD").decode().strip()
        self.git(
            self.repo,
            "remote",
            "add",
            "origin",
            "https://github.com/kixelated/test.git",
        )
        self.git(self.repo, "update-ref", f"refs/remotes/origin/{base}", initial)
        self.git(self.wt, "checkout", "-qb", "feature", f"origin/{base}")
        (self.wt / "source").write_text("feature")
        self.git(self.wt, "commit", "-qam", "feature")
        head = self.git(self.wt, "rev-parse", "HEAD").decode().strip()
        # A squash has the same patch but different ancestry.
        (self.repo / "source").write_text("feature")
        self.git(self.repo, "commit", "-qam", "squash merge")
        merge = self.git(self.repo, "rev-parse", "HEAD").decode().strip()
        self.git(self.repo, "update-ref", f"refs/remotes/origin/{base}", merge)
        return {
            "headRefName": "feature",
            "headRefOid": head,
            "baseRefName": base,
            "mergeCommit": {"oid": merge},
        }

    def module(self):
        source = self.root / "module"
        self.git(self.repo, "clone", "-q", str(self.repo), str(source))
        self.git(
            self.wt,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(source),
            "moq",
        )
        self.git(self.wt, "commit", "-qm", "module")
        self.git(
            self.repo,
            "branch",
            "with-module",
            self.git(self.wt, "rev-parse", "HEAD").decode().strip(),
        )
        return self.wt / "moq"

    def test_clean_plain_worktree(self):
        self.retire()
        self.assertFalse(self.wt.exists())
        self.assertNotIn("--force", self.executed[-1])

    def test_linked_only_discovery_keeps_stable_repository_handle(self):
        search = self.root / "search"
        search.mkdir()
        first = search / "first"
        second = search / "second"
        self.git(self.repo, "worktree", "move", str(self.wt), str(first))
        self.git(self.repo, "worktree", "add", "-q", "--detach", str(second))
        handles = list(cleanup.repositories([search]))
        self.assertEqual(handles, [self.repo / ".git"])
        for entry in list(cleanup.worktrees(handles[0]))[1:]:
            cleanup.retire(handles[0], entry, False)
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())
        self.assertEqual(len(list(cleanup.worktrees(handles[0]))), 1)

    def test_clean_submodule_single_force(self):
        self.module()
        self.retire()
        self.assertFalse(self.wt.exists())
        self.assertEqual(self.executed[-1].count("--force"), 1)
        self.assertEqual(self.executed[0][-1], str(self.wt / "moq"))

    def test_dirty_and_hidden_untracked_preserved(self):
        self.git(self.wt, "config", "status.showUntrackedFiles", "no")
        (self.wt / "untracked").write_text("keep")
        with self.assertRaises(cleanup.Preserve):
            self.retire()
        self.assertTrue(self.wt.exists())
        self.assertEqual(self.executed, [])

    def test_submodule_ignore_setting_overridden(self):
        module = self.module()
        self.git(self.wt, "config", "submodule.moq.ignore", "all")
        (module / "source").write_text("dirty")
        with self.assertRaises(cleanup.Preserve):
            self.retire()
        self.assertTrue(module.exists())

    def test_submodule_local_only_ref_preserved(self):
        module = self.module()
        self.git(module, "config", "user.name", "Test")
        self.git(module, "config", "user.email", "test@example.com")
        old = self.git(module, "rev-parse", "HEAD").decode().strip()
        self.git(module, "commit", "-qm", "local", "--allow-empty")
        self.git(module, "branch", "local-work")
        self.git(module, "checkout", "-q", "--detach", old)
        with self.assertRaisesRegex(cleanup.Preserve, "local-only"):
            self.retire()

    def test_locked_preserved(self):
        self.git(self.repo, "worktree", "lock", str(self.wt))
        with self.assertRaises(cleanup.Preserve):
            self.retire()
        self.assertEqual(self.executed, [])

    def test_active_path_with_metacharacters_preserved(self):
        with (
            patch.object(cleanup, "processes", return_value=[self.wt / "source"]),
            self.assertRaises(cleanup.Preserve),
        ):
            self.retire()

    def test_unique_detached_commit_preserved(self):
        self.git(self.wt, "commit", "-qm", "local", "--allow-empty")
        with self.assertRaises(cleanup.Preserve):
            self.retire()

    def test_gone_upstream_keeps_branch(self):
        self.git(self.wt, "checkout", "-qb", "finished")
        self.git(self.wt, "commit", "-qm", "local", "--allow-empty")
        self.git(self.wt, "config", "remote.origin.url", str(self.repo))
        self.git(
            self.wt,
            "config",
            "remote.origin.fetch",
            "+refs/heads/*:refs/remotes/origin/*",
        )
        self.git(self.wt, "config", "branch.finished.remote", "origin")
        self.git(self.wt, "config", "branch.finished.merge", "refs/heads/finished")
        self.retire()
        self.assertTrue(self.git(self.repo, "rev-parse", "refs/heads/finished"))

    def test_active_managed_target_outside_checkout_preserved(self):
        target = self.root / "managed-target"
        with (
            patch.object(
                cleanup, "workspace_targets", return_value={self.wt: [target]}
            ),
            patch.object(cleanup, "processes", return_value=[target / "binary"]),
            self.assertRaises(cleanup.Preserve),
        ):
            self.retire()
        self.assertEqual(self.executed, [])

    def test_unrelated_active_target_does_not_block_retirement(self):
        with patch.object(
            cleanup, "processes", return_value=[self.root / "other-target/binary"]
        ):
            self.retire()
        self.assertFalse(self.wt.exists())

    def test_activity_started_after_snapshot_preserves_worktree(self):
        with (
            patch.object(cleanup, "processes", return_value=[self.wt / "source"]),
            self.assertRaises(cleanup.Preserve),
        ):
            cleanup.retire(self.repo, self.entry(), False, activity=[])
        self.assertEqual(self.executed, [])

    def test_failed_activity_inspection_preserves_checkout(self):
        with (
            patch.object(
                cleanup, "processes", side_effect=cleanup.Preserve("inspection failed")
            ),
            self.assertRaises(cleanup.Preserve),
        ):
            self.retire()
        self.assertEqual(self.executed, [])

    def test_cache_failure_stops_removal(self):
        with (
            patch.object(
                cleanup, "execute", side_effect=subprocess.CalledProcessError(1, "mbx")
            ),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            self.retire()
        self.assertTrue(self.wt.exists())

    def test_dry_run_keeps_worktree(self):
        self.module()
        self.retire(dry=True)
        self.assertTrue(self.wt.exists())

    def test_ignored_local_state_preserved(self):
        self.git(self.wt, "config", "core.excludesFile", str(self.root / "ignore"))
        (self.root / "ignore").write_text(".env\n")
        (self.wt / ".env").write_text("local")
        with self.assertRaisesRegex(cleanup.Preserve, "ignored local data"):
            self.retire()
        self.assertTrue((self.wt / ".env").exists())
        self.assertTrue(
            any(command[:3] == ["mbx", "cache", "remove"] for command in self.executed)
        )
        self.assertFalse(any(command[0] == "git" for command in self.executed))

    def test_squash_merge_with_inherited_upstream(self):
        pr = self.feature()
        self.assertFalse(cleanup.ancestor(self.repo, pr["headRefOid"], "origin/main"))
        with patch.object(cleanup, "merged_pull_requests", return_value=[pr]):
            self.retire()
        self.assertFalse(self.wt.exists())
        self.assertTrue(self.git(self.repo, "rev-parse", "refs/heads/feature"))

    def test_renamed_local_branch_uses_merged_commit(self):
        pr = self.feature()
        self.git(self.wt, "branch", "-m", "local-review-alias")
        with patch.object(cleanup, "merged_pull_requests", return_value=[pr]):
            self.retire()
        self.assertFalse(self.wt.exists())
        self.assertEqual(self.git(self.repo, "rev-parse", "local-review-alias").decode().strip(), pr["headRefOid"])

    def test_earlier_iteration_of_merged_pr_is_complete(self):
        pr = self.feature()
        earlier = pr["headRefOid"]
        self.git(self.wt, "commit", "-qm", "review follow-up", "--allow-empty")
        pr["headRefOid"] = self.git(self.wt, "rev-parse", "HEAD").decode().strip()
        self.git(self.wt, "reset", "--hard", earlier)
        with patch.object(cleanup, "merged_pull_requests", return_value=[pr]):
            self.retire()
        self.assertFalse(self.wt.exists())

    def test_missing_pr_head_object_provides_no_completion(self):
        pr = self.feature()
        pr["headRefOid"] = "f" * 40
        with patch.object(cleanup, "merged_pull_requests", return_value=[pr]):
            with self.assertRaisesRegex(cleanup.Preserve, "no verified completion"):
                self.retire()
        self.assertEqual(self.executed, [])

    def test_base_rewrite_invalidates_cached_pr_proof(self):
        pr = self.feature()
        with patch.object(cleanup, "merged_pull_requests", return_value=[pr]):
            cleanup.eligible(self.repo, self.entry())
            parent = self.git(self.repo, "rev-parse", "HEAD^").decode().strip()
            self.git(self.repo, "update-ref", "refs/remotes/origin/main", parent)
            with self.assertRaisesRegex(cleanup.Preserve, "no verified completion"):
                self.retire()
        self.assertEqual(self.executed, [])

    def test_release_pr_uses_actual_base(self):
        pr = self.feature("release")
        with patch.object(cleanup, "merged_pull_requests", return_value=[pr]):
            self.retire()
        self.assertFalse(self.wt.exists())

    def test_commits_after_merge_preserved(self):
        pr = self.feature()
        self.git(self.wt, "commit", "-qm", "more work", "--allow-empty")
        with (
            patch.object(cleanup, "merged_pull_requests", return_value=[pr]),
            self.assertRaisesRegex(cleanup.Preserve, "no verified completion"),
        ):
            self.retire()
        self.assertEqual(self.executed, [])

    def test_unmerged_or_closed_pr_preserved(self):
        self.feature()
        with self.assertRaisesRegex(cleanup.Preserve, "no verified completion"):
            self.retire()
        self.assertEqual(self.executed, [])

    def test_merge_no_longer_on_base_preserved(self):
        pr = self.feature()
        parent = self.git(self.repo, "rev-parse", "HEAD^").decode().strip()
        self.git(self.repo, "update-ref", "refs/remotes/origin/main", parent)
        with (
            patch.object(cleanup, "merged_pull_requests", return_value=[pr]),
            self.assertRaises(cleanup.Preserve),
        ):
            self.retire()

    def test_deleted_inherited_base_is_not_gone_feature(self):
        self.feature()
        self.git(self.repo, "update-ref", "-d", "refs/remotes/origin/main")
        with self.assertRaises(cleanup.Preserve):
            self.retire()

    def test_unfetched_remote_cannot_prove_gone_branch(self):
        self.feature()
        self.git(
            self.repo, "remote", "add", "fork", "https://github.com/kixelated/fork.git"
        )
        self.git(self.repo, "config", "branch.feature.remote", "fork")
        self.git(self.repo, "config", "branch.feature.merge", "refs/heads/feature")
        with self.assertRaises(cleanup.Preserve):
            self.retire()

    def test_pr_inspection_failure_preserves_checkout(self):
        self.feature()
        with (
            patch.object(
                cleanup,
                "merged_pull_requests",
                side_effect=cleanup.Preserve("API failed"),
            ),
            self.assertRaises(cleanup.Preserve),
        ):
            self.retire()
        self.assertEqual(self.executed, [])

    def test_local_data_archived_and_verified_before_removal(self):
        source = self.ignored("doc/draft/", "doc/draft/idea.md", "irreplaceable draft")
        source.chmod(0o600)
        expected = cleanup.fingerprint(source)
        self.retire(archive=True)
        self.assertFalse(self.wt.exists())
        archives = list((self.root / "state/worktree-clean/archives").iterdir())
        self.assertEqual(len(archives), 1)
        manifest = json.loads((archives[0] / "manifest.json").read_text())
        self.assertEqual(manifest["worktree"], str(self.wt))
        self.assertEqual(manifest["files"]["doc/draft/idea.md"], expected)
        self.assertEqual(
            cleanup.fingerprint(archives[0] / "files/doc/draft/idea.md"), expected
        )

    def test_ignored_submodule_data_archived(self):
        module = self.module()
        (self.root / "ignore").write_text(".env\n")
        self.git(module, "config", "core.excludesFile", str(self.root / "ignore"))
        (module / ".env").write_text("submodule state")
        self.retire(archive=True)
        backups = list(
            (self.root / "state/worktree-clean/archives").glob("*/files/moq/.env")
        )
        self.assertEqual(backups[0].read_text(), "submodule state")

    def test_archive_symlink_preserves_link_without_following(self):
        link = self.ignored(".env", ".env")
        link.unlink()
        link.symlink_to("/not/a/real/secret")
        self.retire(archive=True)
        backup = next(
            (self.root / "state/worktree-clean/archives").glob("*/files/.env")
        )
        self.assertEqual(os.readlink(backup), "/not/a/real/secret")

    def test_archive_copy_failure_keeps_original(self):
        source = self.ignored(".env", ".env")
        with (
            patch.object(cleanup.shutil, "copy2", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
        ):
            self.retire(archive=True)
        self.assertEqual(source.read_text(), "local")
        self.assertFalse(any(command[0] == "git" for command in self.executed))

    def test_archive_corruption_keeps_original(self):
        source = self.ignored(".env", ".env")

        def corrupt(source, target, **kwargs):
            target.write_text("corrupt")

        with (
            patch.object(cleanup.shutil, "copy2", side_effect=corrupt),
            self.assertRaisesRegex(cleanup.Preserve, "verification failed"),
        ):
            self.retire(archive=True)
        self.assertEqual(source.read_text(), "local")

    def test_source_change_after_archive_keeps_worktree(self):
        source = self.ignored(".env", ".env")
        original = cleanup.archive_local_data

        def archive(*args):
            saved = original(*args)
            source.write_text("new local work")
            return saved

        with (
            patch.object(cleanup, "archive_local_data", side_effect=archive),
            self.assertRaisesRegex(cleanup.Preserve, "changed during archive"),
        ):
            self.retire(archive=True)
        self.assertEqual(source.read_text(), "new local work")

    def test_archive_dry_run_does_not_write_backups(self):
        self.ignored(".env", ".env")
        self.retire(dry=True, archive=True)
        self.assertTrue(self.wt.exists())
        self.assertFalse((self.root / "state").exists())

    def test_independent_nested_repository_inside_artifact_preserved(self):
        source = self.ignored("target/", "target/nested/notes", "local work")
        self.git(source.parent, "init", "-q")
        with self.assertRaisesRegex(cleanup.Preserve, "nested Git repository"):
            self.retire(archive=True)
        self.assertEqual(source.read_text(), "local work")
        self.assertEqual(self.executed, [])

    def test_ignored_tree_archives_files_and_directory_symlinks(self):
        self.ignored(".scratch/", ".scratch/nested/notes.md", "keep this draft")
        link = self.wt / ".scratch/linked-directory"
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret").write_text("never traverse")
        link.symlink_to(outside, target_is_directory=True)
        self.retire(archive=True)
        backup = next((self.root / "state/worktree-clean/archives").glob("*/files/.scratch"))
        self.assertEqual((backup / "nested/notes.md").read_text(), "keep this draft")
        self.assertTrue((backup / "linked-directory").is_symlink())
        self.assertEqual((outside / "secret").read_text(), "never traverse")

    def test_unmarked_target_local_files_are_archived(self):
        self.ignored("target/", "target/review.md", "valuable review notes")
        (self.wt / "target/debug").mkdir()
        (self.wt / "target/debug/object").write_text("unknown build state")
        self.retire(archive=True)
        backup = next((self.root / "state/worktree-clean/archives").glob("*/files/target"))
        self.assertEqual((backup / "review.md").read_text(), "valuable review notes")
        self.assertEqual((backup / "debug/object").read_text(), "unknown build state")

    def test_agent_scratch_is_disposable(self):
        self.ignored(".tmp/", ".tmp/pr-body.md", "draft")
        self.retire()
        self.assertFalse(self.wt.exists())
        self.assertFalse((self.root / "state").exists())

    def test_marked_cargo_target_is_reproducible(self):
        self.ignored("target/", "target/CACHEDIR.TAG", "Signature: 8a477f597d28d172789f06886806bc55\n")
        (self.wt / "target/debug").mkdir()
        (self.wt / "target/debug/object").write_text("compiled output")
        self.retire(archive=True)
        self.assertFalse(self.wt.exists())
        self.assertFalse((self.root / "state").exists())

    def test_bare_repository_inside_ignored_artifacts_preserved(self):
        self.ignored("target/", "target/cache/notes", "local")
        self.git(self.wt, "init", "--bare", "target/cache/history.git")
        with self.assertRaisesRegex(cleanup.Preserve, "nested Git repository"):
            self.retire(archive=True)
        self.assertEqual(self.executed, [])

    def test_archive_mode_still_protects_submodule_local_history(self):
        module = self.module()
        self.git(module, "config", "user.name", "Test")
        self.git(module, "config", "user.email", "test@example.com")
        old = self.git(module, "rev-parse", "HEAD").decode().strip()
        self.git(module, "commit", "-qm", "local", "--allow-empty")
        self.git(module, "branch", "local-work")
        self.git(module, "checkout", "-q", "--detach", old)
        with self.assertRaisesRegex(cleanup.Preserve, "local-only"):
            self.retire(archive=True)


class PullRequestEvidenceTest(unittest.TestCase):
    def setUp(self):
        cleanup.pull_request_evidence.cache_clear()
        self.addCleanup(cleanup.pull_request_evidence.cache_clear)

    def test_paginated_exact_head_evidence(self):
        prs = [
            {"headRefName": "first", "headRefOid": "a" * 40},
            {"headRefName": "last", "headRefOid": "b" * 40},
        ]
        pages = [
            {"data": {"repository": {"pullRequests": {"nodes": [pr]}}}} for pr in prs
        ]
        result = subprocess.CompletedProcess([], 0, json.dumps(pages), "")
        with (
            patch.object(
                cleanup, "text", return_value="git@github.com:kixelated/test.git"
            ),
            patch.object(cleanup.subprocess, "run", return_value=result) as run,
        ):
            self.assertEqual(cleanup.merged_pull_requests(Path("repo")), prs)
            self.assertEqual(cleanup.merged_pull_requests(Path("repo")), prs)
        run.assert_called_once()
        self.assertIn("--paginate", run.call_args.args[0])

    def test_api_failure_cached_and_protected(self):
        result = subprocess.CompletedProcess([], 1, "", "authentication failed")
        with (
            patch.object(
                cleanup, "text", return_value="https://github.com/kixelated/test"
            ),
            patch.object(cleanup.subprocess, "run", return_value=result) as run,
        ):
            for _ in range(2):
                with self.assertRaisesRegex(cleanup.Preserve, "authentication failed"):
                    cleanup.merged_pull_requests(Path("repo"))
        run.assert_called_once()

    def test_malformed_api_response_protected(self):
        result = subprocess.CompletedProcess([], 0, '[{"errors": ["denied"]}]', "")
        with (
            patch.object(
                cleanup, "text", return_value="https://github.com/kixelated/test"
            ),
            patch.object(cleanup.subprocess, "run", return_value=result),
            self.assertRaisesRegex(cleanup.Preserve, "invalid merged"),
        ):
            cleanup.merged_pull_requests(Path("repo"))


@unittest.skipUnless(
    sys.platform.startswith("linux"), "systemd installer is Linux-only"
)
class InstallTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.commands = self.root / "commands"
        self.commands.mkdir()
        self.log = self.root / "commands.log"
        for command in ("mise", "git", "systemctl"):
            script = self.commands / command
            script.write_text(
                f'#!/bin/sh\nprintf \'%s\\n\' "{command} $*" >> "$INSTALL_LOG"\n'
            )
            script.chmod(0o755)
        self.env = {
            **os.environ,
            "HOME": str(self.root / "home"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "PATH": f"{self.commands}:/usr/bin:/bin",
            "INSTALL_LOG": str(self.log),
        }
        Path(self.env["HOME"]).mkdir()
        self.repo = Path(__file__).resolve().parents[1]

    def install(self):
        return subprocess.run(
            ["bash", str(self.repo / "install")],
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_full_install_keeps_cleanup_manual_and_is_repeatable(self):
        for _ in range(2):
            self.install()
        units = Path(self.env["XDG_CONFIG_HOME"]) / "systemd/user"
        self.assertEqual(
            (units / "worktree-clean.service").resolve(),
            self.repo / "systemd/worktree-clean.service",
        )
        self.assertFalse((units / "worktree-clean.timer").exists())
        self.assertEqual(
            (Path(self.env["HOME"]) / ".local/bin/clean-worktrees.py").resolve(),
            self.repo / "bin/clean-worktrees.py",
        )
        calls = self.log.read_text().splitlines()
        self.assertEqual(calls.count("systemctl --user daemon-reload"), 2)
        self.assertFalse(any("enable --now" in call for call in calls))

    def test_install_removes_dangling_legacy_timer(self):
        units = Path(self.env["XDG_CONFIG_HOME"]) / "systemd/user"
        (units / "timers.target.wants").mkdir(parents=True)
        missing = self.repo / "systemd/worktree-clean.timer"
        (units / "worktree-clean.timer").symlink_to(missing)
        (units / "timers.target.wants/worktree-clean.timer").symlink_to(missing)
        self.install()
        self.assertFalse((units / "worktree-clean.timer").is_symlink())
        self.assertFalse((units / "timers.target.wants/worktree-clean.timer").is_symlink())
        self.assertIn("systemctl --user stop worktree-clean.timer", self.log.read_text())

    def test_no_user_manager_skips_service_and_finishes_install(self):
        (self.commands / "systemctl").write_text("#!/bin/sh\nexit 1\n")
        result = self.install()
        self.assertIn("Skipping worktree cleanup service", result.stdout)
        self.assertFalse((Path(self.env["XDG_CONFIG_HOME"]) / "systemd/user").exists())
        self.assertTrue((Path(self.env["HOME"]) / ".codex/bash-env.sh").is_symlink())
        self.assertIn("git submodule update --init --remote", self.log.read_text())


class ShellDispatchTest(unittest.TestCase):
    def test_normal_run_avoids_cargo_repository_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = root / "commands"
            commands.mkdir()
            log = root / "calls"
            stubs = {
                "lsof": "printf 'n/unused\\n'",
                "find": 'printf "find\\n" >> "$DISPATCH_LOG"',
                "python3": 'printf "%s\\n" "$*" >> "$DISPATCH_LOG"',
            }
            for name, body in stubs.items():
                path = commands / name
                path.write_text("#!/bin/sh\n" + body + "\n")
                path.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{commands}:/usr/bin:/bin",
                "DISPATCH_LOG": str(log),
            }
            script = Path(__file__).resolve().parents[1] / "bin/clean.sh"
            for flags in ([], ["--targets"]):
                subprocess.run(
                    [
                        "bash",
                        str(script),
                        "--dry-run",
                        "--root",
                        str(root),
                        *flags,
                    ],
                    env=env,
                    check=True,
                    capture_output=True,
                )
                calls = log.read_text().splitlines()
                self.assertEqual("find" in calls, bool(flags))
                self.assertIn("--archive-local-data", calls[0])
                log.write_text("")


if __name__ == "__main__":
    unittest.main()
