from __future__ import annotations
import os
from typing import Optional, Tuple
from git import Repo, InvalidGitRepositoryError, NoSuchPathError, GitCommandError


POSSIBLE_BRANCHES = ("master", "main")


def clone_or_open_repo(repo_url: str, workdir: str, branch: str = "master") -> Repo:
    if os.path.isdir(os.path.join(workdir, ".git")):
        try:
            repo = Repo(workdir)
            return repo
        except (InvalidGitRepositoryError, NoSuchPathError):
            pass
    # fresh clone with branch fallbacks
    if os.path.isdir(workdir):
        try:
            for root, dirs, files in os.walk(workdir, topdown=False):
                for name in files:
                    os.remove(os.path.join(root, name))
                for name in dirs:
                    os.rmdir(os.path.join(root, name))
        except Exception:
            pass
    os.makedirs(workdir, exist_ok=True)
    last_error: Optional[Exception] = None
    candidates = [branch] + [b for b in POSSIBLE_BRANCHES if b != branch] + [None]
    for br in candidates:
        try:
            if br:
                return Repo.clone_from(repo_url, workdir, branch=br)
            else:
                return Repo.clone_from(repo_url, workdir)
        except GitCommandError as e:
            last_error = e
            continue
    # if all failed
    if last_error:
        raise last_error
    return Repo(workdir)


def pull_latest(repo: Repo, branch: str = "master") -> Tuple[Optional[str], Optional[str]]:
    current_head = repo.head.commit.hexsha if repo.head.is_valid() else None
    origin = repo.remotes.origin
    origin.fetch()
    try:
        repo.git.checkout(branch)
    except GitCommandError:
        for b in POSSIBLE_BRANCHES:
            try:
                repo.git.checkout(b)
                branch = b
                break
            except GitCommandError:
                continue
    result = origin.pull(branch)
    new_head = repo.head.commit.hexsha if repo.head.is_valid() else None
    return current_head, new_head
