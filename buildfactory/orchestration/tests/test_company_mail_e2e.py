"""Offline two-Company mail flow: claim -> router -> journal -> CEO notification."""

from email.message import EmailMessage

from orchestration.company_hub import CompanyHub
from orchestration.method_adapter import ActorContext
from peripheral.email.poller import MockBackend, run_once


CEO = ActorContext("ceo", "ceo")


def _request(request_id, name):
    return {
        "version": 1,
        "request_id": request_id,
        "method": "claim_company_mailbox",
        "payload": {"name": name},
    }


def _mail(subject):
    message = EmailMessage()
    message["From"] = "service@example.test"
    message["Subject"] = subject
    message.set_content(f"body for {subject}")
    return message.as_bytes()


def _external_events(hub):
    return [
        event
        for event in hub.inbox.peek("ceo")
        if event["body"]["type"] == "external_event"
    ]


def test_two_company_mail_is_routed_and_notified_in_isolation(
    tmp_path, department_specs
):
    global_root = tmp_path / "global-mail"
    companies = tmp_path / "companies"
    acme = CompanyHub(
        companies / "acme",
        company_id="acme",
        mail_global_root=global_root,
        department_specs_path=department_specs,
    )
    bravo = CompanyHub(
        companies / "bravo",
        company_id="bravo",
        mail_global_root=global_root,
        department_specs_path=department_specs,
    )
    assert acme.call(CEO, _request("claim-acme", "maya"))["ok"] is True
    assert bravo.call(CEO, _request("claim-bravo", "billing"))["ok"] is True

    backend = MockBackend()
    backend.add("inbox/acme.eml", _mail("Acme code"), {"to": "maya@foundagent.net"})
    backend.add(
        "inbox/bravo.eml",
        _mail("Bravo code"),
        {"to": "billing@foundagent.net"},
    )
    timestamps = iter((100.0, 200.0))

    stats = run_once(
        backend,
        registry_root=global_root,
        companies_root=companies,
        clock=lambda: next(timestamps),
    )
    acme.tick()
    bravo.tick()

    assert stats == {"processed": 2, "unmatched": 0, "deferred": 0}
    assert [row["subject"] for row in acme.mail_store.peek()] == ["Acme code"]
    assert [row["subject"] for row in bravo.mail_store.peek()] == ["Bravo code"]
    assert [event["body"]["data"]["address"] for event in _external_events(acme)] == [
        "maya@foundagent.net"
    ]
    assert [
        event["body"]["data"]["address"] for event in _external_events(bravo)
    ] == ["billing@foundagent.net"]
    assert "Bravo code" not in str(_external_events(acme))
    assert "Acme code" not in str(_external_events(bravo))
