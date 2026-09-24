import subprocess

from vitruvius_hoard.ingest.git import clone_or_pull, current_commit, git_available


def test_git_available_true_in_this_environment():
    assert git_available() is True


def test_clone_or_pull_into_local_repo(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=origin, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=origin, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=origin, check=True)
    (origin / "README.md").write_text("# Hello\n")
    subprocess.run(["git", "add", "."], cwd=origin, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=origin, check=True)

    dest = tmp_path / "dest"
    ok, message, commit = clone_or_pull(str(origin), dest)
    assert ok is True
    assert (dest / "README.md").is_file()
    assert commit is not None and len(commit) == 40


def test_clone_or_pull_twice_pulls_second_time(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=origin, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=origin, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=origin, check=True)
    (origin / "a.md").write_text("a")
    subprocess.run(["git", "add", "."], cwd=origin, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=origin, check=True)

    dest = tmp_path / "dest"
    ok1, _, _ = clone_or_pull(str(origin), dest)
    ok2, message2, _ = clone_or_pull(str(origin), dest)
    assert ok1 and ok2
    assert (dest / ".git").is_dir()


def test_clone_or_pull_bad_url_fails_gracefully(tmp_path):
    ok, message, commit = clone_or_pull("/no/such/repo/at/all", tmp_path / "dest")
    assert ok is False
    assert commit is None
    assert message


def test_current_commit_none_when_not_a_repo(tmp_path):
    assert current_commit(tmp_path) is None
