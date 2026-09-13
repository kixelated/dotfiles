import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
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

    def retire(self, dry=False):
        cleanup.retire(self.repo, self.entry(), dry)

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
        with patch.object(cleanup, "processes", return_value=[self.wt / "source"]):
            with self.assertRaises(cleanup.Preserve):
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
        ):
            with self.assertRaises(cleanup.Preserve):
                self.retire()
        self.assertEqual(self.executed, [])

    def test_unrelated_active_target_does_not_block_retirement(self):
        with patch.object(
            cleanup, "processes", return_value=[self.root / "other-target/binary"]
        ):
            self.retire()
        self.assertFalse(self.wt.exists())

    def test_failed_activity_inspection_preserves_checkout(self):
        with patch.object(
            cleanup, "processes", side_effect=cleanup.Preserve("inspection failed")
        ):
            with self.assertRaises(cleanup.Preserve):
                self.retire()
        self.assertEqual(self.executed, [])

    def test_cache_failure_stops_removal(self):
        with patch.object(
            cleanup, "execute", side_effect=subprocess.CalledProcessError(1, "mbx")
        ):
            with self.assertRaises(subprocess.CalledProcessError):
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


if __name__ == "__main__":
    unittest.main()
