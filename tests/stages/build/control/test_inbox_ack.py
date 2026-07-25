"""V7 Hub-owned Inbox: explicit root plus peek_one / ack_one / wait.

ack-after-process means a crash BEFORE ack redelivers the event (never drops);
peek never consumes; wait blocks without consuming. Pure python."""

import pytest

from hacksome.stages.build.control.inbox import CEO_KEY, FileInbox, make_ime


def _box(tmp_path):
    return FileInbox(root=tmp_path)


def test_file_inbox_requires_an_explicit_control_plane_root():
    with pytest.raises(TypeError):
        FileInbox()


def test_peek_does_not_advance_cursor(tmp_path):
    box = _box(tmp_path)
    box.append(CEO_KEY, make_ime(to=CEO_KEY, text="a", body="one"))
    assert box.peek_one(CEO_KEY)["body"] == "one"
    assert box.peek_one(CEO_KEY)["body"] == "one"   # same event — cursor untouched


def test_ack_advances_exactly_one(tmp_path):
    box = _box(tmp_path)
    box.append(CEO_KEY, make_ime(to=CEO_KEY, text="a", body="one"))
    box.append(CEO_KEY, make_ime(to=CEO_KEY, text="b", body="two"))
    assert box.peek_one(CEO_KEY)["body"] == "one"
    box.ack_one(CEO_KEY)
    assert box.peek_one(CEO_KEY)["body"] == "two"
    box.ack_one(CEO_KEY)
    assert box.peek_one(CEO_KEY) is None


def test_crash_before_ack_redelivers(tmp_path):
    box = _box(tmp_path)
    box.append(CEO_KEY, make_ime(to=CEO_KEY, text="a", body="work"))
    assert box.peek_one(CEO_KEY)["body"] == "work"   # processed but NOT acked
    box2 = FileInbox(root=tmp_path)                   # crash + restart
    assert box2.peek_one(CEO_KEY)["body"] == "work"   # redelivered, not lost
    box2.ack_one(CEO_KEY)
    assert box2.peek_one(CEO_KEY) is None


def test_wait_true_when_ready_false_on_timeout_and_non_consuming(tmp_path):
    box = _box(tmp_path)
    assert box.wait(CEO_KEY, 0.01) is False
    box.append(CEO_KEY, make_ime(to=CEO_KEY, text="a", body="hi"))
    assert box.wait(CEO_KEY, 0.01) is True
    assert box.peek_one(CEO_KEY)["body"] == "hi"      # wait did not consume


def test_consumed_lookup_is_read_only_and_confined_before_cursor(tmp_path):
    box = _box(tmp_path)
    first = make_ime(to=CEO_KEY, text="a", body="one")
    second = make_ime(to=CEO_KEY, text="b", body="two")
    box.append(CEO_KEY, first)
    box.append(CEO_KEY, second)

    assert box.was_consumed(CEO_KEY, first["id"]) is False
    box.ack_one(CEO_KEY)
    assert box.was_consumed(CEO_KEY, first["id"]) is True
    assert box.was_consumed(CEO_KEY, second["id"]) is False
    assert box.peek_one(CEO_KEY)["id"] == second["id"]
