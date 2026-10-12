"""STUB owned by the WORK agent. Replace with the real module (see dev/DESIGN.md)."""

from __future__ import annotations


def acquire(ctx, seat, task_id, patterns):
    raise NotImplementedError


def release_task(ctx, task_id):
    raise NotImplementedError


def release_all(ctx, seat):
    raise NotImplementedError


def active(ctx, seat=None):
    raise NotImplementedError


def holder(ctx, path):
    raise NotImplementedError


def check_edit(ctx, seat, path):
    raise NotImplementedError
