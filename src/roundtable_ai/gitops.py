"""STUB owned by the WORK agent. Replace with the real module (see dev/DESIGN.md)."""

from __future__ import annotations


def is_git(ctx):
    raise NotImplementedError


def ensure_worktree(ctx, handle):
    raise NotImplementedError


def dirty_files(path):
    raise NotImplementedError


def head(path):
    raise NotImplementedError


def changed_files(ctx, task_row):
    raise NotImplementedError


def diff_text(ctx, task_row, max_lines=None):
    raise NotImplementedError


def hunk_map(ctx, task_row):
    raise NotImplementedError


def merge_task(ctx, task_row):
    raise NotImplementedError


def known_files(ctx):
    raise NotImplementedError


def install_guard(ctx):
    raise NotImplementedError


def guard_check(ctx, worktree_path, staged):
    raise NotImplementedError
