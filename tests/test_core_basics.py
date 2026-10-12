"""Core foundation: init, config, seats, identity, STOP, utilities."""

from __future__ import annotations

import pytest

from roundtable_ai import config, errors, project, util
from roundtable_ai.errors import RTError


def test_init_creates_ignored_home(rt, repo):
    assert (repo / ".roundtable" / "roundtable.db").exists()
    assert (repo / ".roundtable" / ".gitignore").read_text().strip().endswith("*")
    # the main working copy stays clean
    import subprocess

    out = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert out.strip() == ""


def test_init_twice_refused(rt, repo):
    with pytest.raises(RTError) as e:
        project.init_project(repo)
    assert e.value.code == errors.CONFLICT


def test_init_in_subfolder_refused(repo):
    sub = repo / "src"
    with pytest.raises(RTError) as e:
        project.init_project(sub)
    assert "top folder" in (e.value.hint or "")


def test_init_without_git(rt_nogit):
    assert (rt_nogit.home / "roundtable.db").exists()


def test_seat_add_list_and_reserved(rt):
    res = rt.add_seat("opus")
    assert "seat opus added" in res.text
    rt.add_seat("sol61", model="gpt-6.1-sol", app="codex-cli")
    out = rt.human("seat.list").text
    assert "opus" in out and "sol61" in out and "openai" in out
    e = rt.error(rt.add_seat, "human")
    assert e.code == errors.INVALID
    e = rt.error(rt.add_seat, "opus")
    assert e.code == errors.CONFLICT
    e = rt.error(rt.add_seat, "Bad Name!")
    assert e.code == errors.INVALID


def test_claude_app_seat_cannot_build(rt):
    res = rt.add_seat("fable", model="claude-fable-5", app="claude-app")
    assert "plans and reviews only" in res.text
    row = rt.q("SELECT roles FROM seats WHERE handle='fable'")[0]
    assert "build" not in row["roles"]


def test_join_key_and_live_conflict(rt):
    rt.add_seat("opus")
    key = rt.join("opus")
    assert len(key) == 6
    res = rt.keyed(key, "seat.list")
    assert res.text.startswith("[rt:")
    e = rt.error(rt.join, "opus")
    assert e.code == errors.CONFLICT and "rt seat release opus" in e.hint
    rt.human("seat.release", handle="opus")
    key2 = rt.join("opus")
    assert key2 != key
    e = rt.error(rt.keyed, key, "seat.list")
    assert e.code == errors.NEED_JOIN


def test_no_seat_means_need_join(rt):
    from roundtable_ai import dispatch

    with pytest.raises(RTError) as e:
        dispatch.call("seat.list", {}, home=rt.home, as_human=False)
    assert e.value.code == errors.NEED_JOIN


def test_human_only_and_seat_only(rt):
    rt.add_seat("opus")
    e = rt.error(rt.seat, "opus", "seat.pause", handle="opus")
    assert e.code == errors.FORBIDDEN


def test_unknown_param_refused(rt):
    e = rt.error(rt.human, "seat.list", bogus=1)
    assert e.code == errors.INVALID and "bogus" in e.message


def test_freeze_blocks_seats(rt):
    rt.add_seat("opus")
    ctx = rt.ctx()
    with ctx.tx():
        ctx.db.meta_set("frozen", "1")
        ctx.db.meta_set("frozen_reason", "lunch")
    ctx.close()
    # seat.list is frozen_ok, join too
    rt.seat("opus", "seat.list")


def test_pause_returns_tasks(rt):
    rt.add_seat("opus")
    ctx = rt.ctx()
    with ctx.tx():
        ctx.db.execute(
            "INSERT INTO tasks(id,title,status,owner,created_at,updated_at) VALUES ('T1','x','claimed','opus',?,?)",
            (util.now(), util.now()),
        )
    ctx.close()
    res = rt.human("seat.pause", handle="opus")
    assert "T1" in res.text
    assert rt.q("SELECT status FROM tasks WHERE id='T1'")[0]["status"] == "ready"
    e = rt.error(rt.seat, "opus", "seat.list")
    assert e.code == errors.STATE


def test_config_set_keeps_comments(rt):
    path = rt.home / "config.toml"
    config.set_value(path, "review.level", "mid")
    text = path.read_text()
    assert 'level = "mid"' in text and "# How much" in text
    assert config.load(path).get("review", "level") == "mid"
    with pytest.raises(RTError):
        config.set_value(path, "review.level", "extreme")
    with pytest.raises(RTError) as e:
        config.set_value(path, "review.levle", "mid")
    assert "review.level" in (e.value.hint or "")


def test_config_typo_refused(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[review]\nlevle = \"mid\"\n")
    with pytest.raises(RTError) as e:
        config.load(p)
    assert "level" in (e.value.hint or "")


def test_newer_schema_refused(rt):
    from roundtable_ai.context import open_ctx

    ctx = rt.ctx()
    with ctx.tx():
        ctx.db.meta_set("schema_version", "99")
    ctx.close()
    with pytest.raises(RTError) as e:
        open_ctx(rt.home)
    assert e.value.code == errors.VERSION and "upgrade" in e.value.hint


@pytest.mark.parametrize(
    "raw,expected",
    [("src\\a.py", "src/a.py"), ("./src/a.py", "src/a.py"), ("src/../lib/x", "lib/x"), ("src/**", "src/**")],
)
def test_norm_path(tmp_path, raw, expected):
    assert util.norm_path(tmp_path, raw) == expected


@pytest.mark.parametrize("raw", ["../etc/passwd", "/etc/passwd", ".git/config", ".roundtable/roundtable.db", "."])
def test_norm_path_rejects(tmp_path, raw):
    with pytest.raises(RTError):
        util.norm_path(tmp_path, raw)


def test_globs_and_overlap():
    assert util.glob_match("src/**", "src/a/b.py")
    assert util.glob_match("src", "src/a.py")
    assert util.glob_match("src/*.py", "src/a.py")
    assert not util.glob_match("src/*.py", "src/a/b.py")
    assert util.glob_match("**/*.py", "a.py")
    assert util.patterns_overlap("src/**", "src/api/x.py")
    assert util.patterns_overlap("src/api/**", "src/**/*.py")
    assert not util.patterns_overlap("docs/**", "src/**")
    assert not util.patterns_overlap("src/a.py", "src/b.py")
    assert util.patterns_overlap("src/*.py", "src/*.ts", ["src/a.py"]) is False


def test_caps():
    with pytest.raises(RTError) as e:
        util.cap_words("one two three", 2, "summary")
    assert e.value.code == errors.TOO_LONG and "2 words" in e.value.hint
