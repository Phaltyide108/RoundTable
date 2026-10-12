"""STUB owned by the WORK agent. Replace with the real module (see dev/DESIGN.md)."""

from __future__ import annotations


def validate_specs(ctx, specs):
    raise NotImplementedError


def materialize(ctx, plan_id, specs):
    raise NotImplementedError


def refresh_ready(ctx):
    raise NotImplementedError


def complete(ctx, task_id):
    raise NotImplementedError


def get(ctx, task_id):
    raise NotImplementedError


def request_changes(ctx, task_id, reviewer):
    raise NotImplementedError
