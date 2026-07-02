"""Canary verdict logic: given the exchanges a canary run recorded and the AIU
it debited, decide whether the Copilot CLI contract still holds. Pure functions
over already-collected data — the live orchestration lives in tools/canary.py.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from ctc import contract
from ctc.metering.extract import extract_total_nano_aiu
from ctc.sentinel import classify_usage


@dataclass
class Verdict:
    verdict: str  # "pass" | "fail"
    failures: list[dict] = field(default_factory=list)
    extracted_nano_aiu: int | None = None


def load_exchanges(ndjson_path: str) -> list[dict]:
    out: list[dict] = []
    with open(ndjson_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _is_billable(ex: dict) -> bool:
    return (ex.get("host") == contract.BILLABLE_HOST
            and (ex.get("method") or "").upper() == contract.BILLABLE_METHOD
            and (ex.get("path") or "").split("?", 1)[0] in contract.BILLABLE_PATHS)


def evaluate(exchanges: list[dict], debited_nano_aiu: int | None) -> Verdict:
    failures: list[dict] = []
    billable = [ex for ex in exchanges if _is_billable(ex)]

    # 1. A billable call happened and succeeded.
    ok_billable = [ex for ex in billable if ex.get("status") == 200]
    if not billable:
        failures.append({"assertion": "billable_succeeded", "detail": "no billable request observed"})
    elif not ok_billable:
        statuses = sorted({ex.get("status") for ex in billable if ex.get("status") is not None})
        failures.append({"assertion": "billable_succeeded", "detail": f"billable statuses={statuses}, none 200"})

    # 2. The metering field is present in a successful billable body.
    # Use classify_usage (the parsed tri-state classifier) instead of substring
    # matching: a body like {"copilot_usage":{"total_nano_aiu":null}} contains
    # the substrings but has no usable numeric value — classify_usage returns
    # "absent" for that case, so field_present stays False correctly.
    extracted = None
    field_present = False
    for ex in ok_billable:
        body = ex.get("body", "") or ""
        content_type = ex.get("response_content_type", "") or ""
        path = ex.get("path", "") or ""
        classification = classify_usage(body, content_type, path)
        if classification != "absent":
            field_present = True
            extracted = extract_total_nano_aiu(body, content_type)
    if ok_billable and not field_present:
        failures.append({"assertion": "metering_field_present",
                         "detail": f"no {'.'.join(contract.METERING_FIELD)} in any billable 200 body"})

    # 3. A non-zero AIU was debited (extraction + debit intact end-to-end).
    if ok_billable and not (debited_nano_aiu and debited_nano_aiu > 0):
        failures.append({"assertion": "nonzero_aiu_debited",
                         "detail": f"debited={debited_nano_aiu} (paid model must debit > 0)"})

    # 4. Every observed host is within the contract's MITM set.
    unexpected = sorted({ex.get("host") for ex in exchanges
                         if ex.get("host") not in contract.EXPECTED_MITM_HOSTS})
    if unexpected:
        failures.append({"assertion": "hosts_within_contract",
                         "detail": f"unexpected hosts: {unexpected}"})

    return Verdict("fail" if failures else "pass", failures, extracted)


def write_status(path: str, verdict: Verdict, ran_at: str, copilot_version: str | None) -> None:
    payload = {
        "ran_at": ran_at,
        "verdict": verdict.verdict,
        "copilot_version": copilot_version,
        "extracted_nano_aiu": verdict.extracted_nano_aiu,
        "failures": verdict.failures,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
