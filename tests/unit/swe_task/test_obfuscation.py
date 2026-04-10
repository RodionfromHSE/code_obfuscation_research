"""Tests for repo-level obfuscation: identity, rope renamer, context manager, deobfuscation."""
import subprocess
import tempfile
from pathlib import Path

from swe_task.obfuscation.identity import RepoIdentity
from swe_task.obfuscation.protocol import RepoObfuscation, RepoObfuscationResult
from swe_task.obfuscation.repo_copy import obfuscated_repo
from swe_task.obfuscation.rope_renamer import RopeRepoRenamer


def _create_fixture_repo(base: Path) -> Path:
    """Create a multi-file Python project for testing cross-file rename."""
    repo = base / "fixture_repo"
    repo.mkdir()
    pkg = repo / "mypackage"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .core import compute\nfrom .models import DataStore\n")
    (pkg / "core.py").write_text(
        "def compute(x, y):\n"
        "    return x + y\n\n"
        "def helper():\n"
        "    return compute(1, 2)\n"
    )
    (pkg / "models.py").write_text(
        "class DataStore:\n"
        "    def fetch(self):\n"
        "        return []\n\n"
        "class _Internal:\n"
        "    pass\n"
    )
    (pkg / "utils.py").write_text(
        "from .core import compute\nfrom .models import DataStore\n\n"
        "def run():\n"
        "    store = DataStore()\n"
        "    return compute(store.fetch(), [])\n"
    )
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_core.py").write_text(
        "from mypackage.core import compute\n\n"
        "def test_compute():\n"
        "    assert compute(1, 2) == 3\n"
    )
    return repo


class TestRepoIdentity:
    def test_conforms_to_protocol(self):
        assert isinstance(RepoIdentity(), RepoObfuscation)

    def test_does_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _create_fixture_repo(Path(tmp))
            original_content = (repo / "mypackage" / "core.py").read_text()
            result = RepoIdentity().obfuscate(repo)
            assert result.symbols_renamed == 0
            assert result.files_modified == 0
            assert (repo / "mypackage" / "core.py").read_text() == original_content


class TestRopeRepoRenamer:
    def test_conforms_to_protocol(self):
        assert isinstance(RopeRepoRenamer(), RepoObfuscation)

    def test_renames_across_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _create_fixture_repo(Path(tmp))
            renamer = RopeRepoRenamer(max_symbols=50)
            result = renamer.obfuscate(repo)

            assert result.symbols_renamed > 0
            assert result.files_modified > 0
            assert "compute" in result.rename_map

            core_text = (repo / "mypackage" / "core.py").read_text()
            assert "compute" not in core_text
            new_name = result.rename_map["compute"]
            assert new_name in core_text

            utils_text = (repo / "mypackage" / "utils.py").read_text()
            assert "compute" not in utils_text
            assert new_name in utils_text

            init_text = (repo / "mypackage" / "__init__.py").read_text()
            assert "compute" not in init_text
            assert new_name in init_text

    def test_renames_classes_across_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _create_fixture_repo(Path(tmp))
            renamer = RopeRepoRenamer(rename_functions=False, rename_classes=True, max_symbols=50)
            result = renamer.obfuscate(repo)

            assert "DataStore" in result.rename_map
            new_cls = result.rename_map["DataStore"]

            models_text = (repo / "mypackage" / "models.py").read_text()
            assert "DataStore" not in models_text
            assert new_cls in models_text

            utils_text = (repo / "mypackage" / "utils.py").read_text()
            assert "DataStore" not in utils_text
            assert new_cls in utils_text

    def test_skips_private_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _create_fixture_repo(Path(tmp))
            renamer = RopeRepoRenamer(rename_classes=True, max_symbols=50)
            result = renamer.obfuscate(repo)
            assert "_Internal" not in result.rename_map

    def test_skips_test_file_definitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _create_fixture_repo(Path(tmp))
            renamer = RopeRepoRenamer(max_symbols=50)
            result = renamer.obfuscate(repo)
            assert "test_compute" not in result.rename_map

    def test_updates_test_file_references(self):
        """Test files should NOT be renamed (definitions), but their references to renamed symbols should update."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = _create_fixture_repo(Path(tmp))
            renamer = RopeRepoRenamer(max_symbols=50)
            result = renamer.obfuscate(repo)

            test_text = (repo / "tests" / "test_core.py").read_text()
            new_compute = result.rename_map["compute"]
            assert f"import {new_compute}" in test_text
            assert "import compute" not in test_text


class TestObfuscatedRepoContextManager:
    def test_creates_copy_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _create_fixture_repo(Path(tmp))
            original_text = (repo / "mypackage" / "core.py").read_text()
            copy_path = None

            with obfuscated_repo(repo, RopeRepoRenamer(max_symbols=50)) as ctx:
                copy_path = ctx.obfuscated_dir
                assert copy_path.exists()
                assert ctx.result.symbols_renamed > 0
                obfus_text = (copy_path / "mypackage" / "core.py").read_text()
                assert obfus_text != original_text

            assert not copy_path.exists()
            assert (repo / "mypackage" / "core.py").read_text() == original_text

    def test_identity_leaves_copy_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _create_fixture_repo(Path(tmp))
            original_text = (repo / "mypackage" / "core.py").read_text()

            with obfuscated_repo(repo, RepoIdentity()) as ctx:
                copy_text = (ctx.obfuscated_dir / "mypackage" / "core.py").read_text()
                assert copy_text == original_text
                assert ctx.result.symbols_renamed == 0


class TestDeobfuscatePatchIdentity:
    def test_returns_patch_unchanged(self):
        patch = "+    return cls_0()\n-    return AppConfig()\n"
        result = RepoObfuscationResult(symbols_renamed=0, files_modified=0)
        assert RepoIdentity().deobfuscate_patch(patch, result) == patch


class TestDeobfuscatePatchRopeRenamer:
    def _make_result(self, rename_map: dict[str, str]) -> RepoObfuscationResult:
        return RepoObfuscationResult(
            symbols_renamed=len(rename_map),
            files_modified=1,
            rename_map=rename_map,
        )

    def test_basic_reverse(self):
        rename_map = {"compute": "func_0", "DataStore": "cls_0"}
        patch = (
            "diff --git a/pkg/core.py b/pkg/core.py\n"
            "--- a/pkg/core.py\n"
            "+++ b/pkg/core.py\n"
            "-    return func_0(1, 2)\n"
            "+    return func_0(1, 2) + cls_0().fetch()\n"
        )
        out = RopeRepoRenamer().deobfuscate_patch(patch, self._make_result(rename_map))
        assert "func_0" not in out
        assert "cls_0" not in out
        assert "compute" in out
        assert "DataStore" in out

    def test_empty_patch(self):
        rename_map = {"compute": "func_0"}
        assert RopeRepoRenamer().deobfuscate_patch("", self._make_result(rename_map)) == ""

    def test_no_rename_map(self):
        patch = "+    return func_0()\n"
        result = RepoObfuscationResult(symbols_renamed=0, files_modified=0)
        assert RopeRepoRenamer().deobfuscate_patch(patch, result) == patch

    def test_longest_first_no_collision(self):
        """cls_1 must not match inside cls_10."""
        rename_map = {"Alpha": "cls_1", "Beta": "cls_10"}
        patch = "cls_10 and cls_1\n"
        out = RopeRepoRenamer().deobfuscate_patch(patch, self._make_result(rename_map))
        assert out == "Beta and Alpha\n"

    def test_word_boundary(self):
        """func_0 inside func_0_extra should not be replaced."""
        rename_map = {"compute": "func_0"}
        patch = "func_0_extra = func_0()\n"
        out = RopeRepoRenamer().deobfuscate_patch(patch, self._make_result(rename_map))
        assert "func_0_extra" in out  # not replaced (not a word boundary)
        assert "= compute()" in out   # replaced

    def test_substring_original_names(self):
        """'compute' renamed to func_0; 'computed_result' is NOT an obfuscated name and must stay."""
        rename_map = {"compute": "func_0"}
        patch = "+    computed_result = func_0(x)\n"
        out = RopeRepoRenamer().deobfuscate_patch(patch, self._make_result(rename_map))
        assert "computed_result" in out  # untouched
        assert "= compute(x)" in out    # reversed

    def test_obfuscated_name_in_string_literal(self):
        """Obfuscated names inside string literals are also reversed (acceptable: we want clean patches)."""
        rename_map = {"setup": "func_0"}
        patch = '+    raise ValueError("func_0 failed")\n'
        out = RopeRepoRenamer().deobfuscate_patch(patch, self._make_result(rename_map))
        assert '"setup failed"' in out

    def test_obfuscated_name_in_comment(self):
        rename_map = {"AppConfig": "cls_0"}
        patch = "+    # initialize cls_0 before use\n"
        out = RopeRepoRenamer().deobfuscate_patch(patch, self._make_result(rename_map))
        assert "initialize AppConfig before use" in out

    def test_agent_creates_new_var_using_obfuscated_prefix(self):
        """Agent creates func_0_result — should NOT be reversed (word boundary protects)."""
        rename_map = {"compute": "func_0"}
        patch = "+    func_0_result = func_0()\n"
        out = RopeRepoRenamer().deobfuscate_patch(patch, self._make_result(rename_map))
        assert "func_0_result" in out   # untouched
        assert "= compute()" in out     # reversed

    def test_multiple_obfuscated_on_same_line(self):
        rename_map = {"compute": "func_0", "DataStore": "cls_0", "run": "func_1"}
        patch = "+    return func_1(cls_0(), func_0(x))\n"
        out = RopeRepoRenamer().deobfuscate_patch(patch, self._make_result(rename_map))
        assert "func_0" not in out
        assert "cls_0" not in out
        assert "func_1" not in out
        assert "run(DataStore(), compute(x))" in out

    def test_diff_context_lines_reversed(self):
        """Context lines (no +/-) in a diff hunk should also be reversed."""
        rename_map = {"compute": "func_0"}
        patch = (
            "@@ -10,3 +10,4 @@\n"
            " def func_0(x, y):\n"
            "     return x + y\n"
            "+    # added line\n"
        )
        out = RopeRepoRenamer().deobfuscate_patch(patch, self._make_result(rename_map))
        assert "def compute(x, y):" in out


def _git_init(repo: Path) -> None:
    """Initialize a git repo and make an initial commit."""
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@test",
         "commit", "-m", "init", "-q"],
        cwd=repo, check=True, capture_output=True,
    )


def _git_diff(repo: Path) -> str:
    return subprocess.run(
        ["git", "diff"], cwd=repo, capture_output=True, text=True, check=True,
    ).stdout


class TestDeobfuscateRoundTrip:
    """End-to-end: obfuscate repo -> simulate agent edit -> deobfuscate patch -> apply to original."""

    def test_roundtrip_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            # 1. create fixture repo with git
            (base / "orig").mkdir()
            repo_orig = _create_fixture_repo(base / "orig")
            _git_init(repo_orig)

            # 2. obfuscate a copy via the context manager
            renamer = RopeRepoRenamer(max_symbols=50)
            with obfuscated_repo(repo_orig, renamer) as ctx:
                obfus_dir = ctx.obfuscated_dir
                result = ctx.result

                assert result.symbols_renamed > 0
                compute_obfus = result.rename_map["compute"]

                # 3. simulate agent: edit the obfuscated file (change return value)
                core = obfus_dir / "mypackage" / "core.py"
                text = core.read_text()
                assert compute_obfus in text
                text = text.replace("return x + y", "return x + y + 1")
                core.write_text(text)

                # 4. get agent's patch (in obfuscated names)
                obfus_patch = _git_diff(obfus_dir)
                assert obfus_patch  # non-empty
                assert compute_obfus in obfus_patch

                # 5. deobfuscate
                clean_patch = renamer.deobfuscate_patch(obfus_patch, result)
                assert compute_obfus not in clean_patch
                assert "compute" in clean_patch
                assert "return x + y + 1" in clean_patch

            # 6. apply clean patch to original repo
            apply_result = subprocess.run(
                ["git", "apply", "--check", "-"],
                input=clean_patch,
                cwd=repo_orig,
                capture_output=True,
                text=True,
            )
            assert apply_result.returncode == 0, f"git apply --check failed: {apply_result.stderr}"

            subprocess.run(
                ["git", "apply", "-"],
                input=clean_patch,
                cwd=repo_orig,
                capture_output=True,
                text=True,
                check=True,
            )

            # 7. verify the change landed on the original repo with original names
            patched_core = (repo_orig / "mypackage" / "core.py").read_text()
            assert "compute" in patched_core
            assert "return x + y + 1" in patched_core

    def test_roundtrip_rename_with_substring_variable(self):
        """Agent adds a variable whose name is a substring of the original (computed_result)."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "orig").mkdir()
            repo_orig = _create_fixture_repo(base / "orig")
            _git_init(repo_orig)

            renamer = RopeRepoRenamer(max_symbols=50)
            with obfuscated_repo(repo_orig, renamer) as ctx:
                result = ctx.result
                compute_obfus = result.rename_map["compute"]

                core = ctx.obfuscated_dir / "mypackage" / "core.py"
                text = core.read_text()
                text = text.replace(
                    "return x + y",
                    f"computed_result = x + y + 1\n    return computed_result",
                )
                core.write_text(text)

                obfus_patch = _git_diff(ctx.obfuscated_dir)
                assert compute_obfus in obfus_patch
                assert "computed_result" in obfus_patch

                clean_patch = renamer.deobfuscate_patch(obfus_patch, result)
                assert "computed_result" in clean_patch  # not mangled
                assert compute_obfus not in clean_patch
                assert "compute" in clean_patch

            apply_result = subprocess.run(
                ["git", "apply", "--check", "-"],
                input=clean_patch, cwd=repo_orig,
                capture_output=True, text=True,
            )
            assert apply_result.returncode == 0, f"git apply failed: {apply_result.stderr}"

            subprocess.run(
                ["git", "apply", "-"],
                input=clean_patch, cwd=repo_orig,
                capture_output=True, text=True, check=True,
            )
            patched = (repo_orig / "mypackage" / "core.py").read_text()
            assert "computed_result = x + y + 1" in patched
            assert "def compute" in patched

    def test_roundtrip_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "orig").mkdir()
            repo_orig = _create_fixture_repo(base / "orig")
            _git_init(repo_orig)

            identity = RepoIdentity()
            with obfuscated_repo(repo_orig, identity) as ctx:
                core = ctx.obfuscated_dir / "mypackage" / "core.py"
                text = core.read_text()
                text = text.replace("return x + y", "return x + y + 1")
                core.write_text(text)

                patch = _git_diff(ctx.obfuscated_dir)
                clean_patch = identity.deobfuscate_patch(patch, ctx.result)
                assert clean_patch == patch

            apply_result = subprocess.run(
                ["git", "apply", "--check", "-"],
                input=clean_patch,
                cwd=repo_orig,
                capture_output=True,
                text=True,
            )
            assert apply_result.returncode == 0
