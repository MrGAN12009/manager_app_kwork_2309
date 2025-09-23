from __future__ import annotations
import os
from typing import Optional, Tuple
from git import Repo, InvalidGitRepositoryError, NoSuchPathError


def clone_or_open_repo(repo_url: str, workdir: str, branch: str = "master") -> Repo:
    if os.path.isdir(os.path.join(workdir, ".git")):
        try:
            repo = Repo(workdir)
        except (InvalidGitRepositoryError, NoSuchPathError):
            # Re-clone if directory is broken
            if os.path.isdir(workdir):
                for root, dirs, files in os.walk(workdir, topdown=False):
                    for name in files:
                        os.remove(os.path.join(root, name))
                    for name in dirs:
                        os.rmdir(os.path.join(root, name))
            repo = Repo.clone_from(repo_url, workdir, branch=branch)
    else:
        os.makedirs(workdir, exist_ok=True)
        repo = Repo.clone_from(repo_url, workdir, branch=branch)
    return repo


def pull_latest(repo: Repo, branch: str = "master") -> Tuple[Optional[str], Optional[str]]:
    current_head = repo.head.commit.hexsha if repo.head.is_valid() else None
    origin = repo.remotes.origin
    origin.fetch()
    repo.git.checkout(branch)
    result = origin.pull(branch)
    new_head = repo.head.commit.hexsha if repo.head.is_valid() else None
    return current_head, new_head
