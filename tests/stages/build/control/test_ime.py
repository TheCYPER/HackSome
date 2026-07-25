"""make_ime / IME envelope tests (peripheral-layer Phase 0): exactly 5 fields,
auto id/time, overrides, and "extension lives in body" (design §2.3). Pure
python, no docker."""

from hacksome.stages.build.control.inbox import make_ime


def test_make_ime_has_exactly_five_fields():
    ime = make_ime(to=None, text="新邮件", body="来自 jordan@acme.com …")
    assert set(ime) == {"id", "time", "to", "text", "body"}


def test_auto_id_and_time_are_filled():
    ime = make_ime(None, "t", "b")
    assert ime["id"] and isinstance(ime["id"], str)
    assert ime["time"] and "T" in ime["time"]          # ISO-8601


def test_ids_are_unique():
    assert make_ime(None, "t", "b")["id"] != make_ime(None, "t", "b")["id"]


def test_overrides_respected():
    ime = make_ime("ceo", "t", "b", id="fixed", ts="2026-01-01T00:00:00+00:00")
    assert ime["id"] == "fixed"
    assert ime["time"] == "2026-01-01T00:00:00+00:00"
    assert ime["to"] == "ceo"


def test_to_can_address_any_agent():
    # per-agent inbox: `to` is general, not CEO-only (R8).
    assert make_ime("writer-7", "t", "b")["to"] == "writer-7"


def test_extension_lives_in_body_not_new_fields():
    # "which goal this answers" + structured data ride INSIDE body.
    ime = make_ime(None, "✅ done", 'goal 8f1c done. data={"outcome":"done"}')
    assert "8f1c" in ime["body"]
    assert set(ime) == {"id", "time", "to", "text", "body"}
