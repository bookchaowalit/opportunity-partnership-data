"""Capture one reviewed public partner-program page through the shared lake runtime."""

import argparse
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

from .cli import resource, validate
from .observability import init_sentry, report_exit


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)


def required_markers(source):
    """Drift markers reviewed alongside the source config (`required_markers`)."""
    markers = source.get("required_markers")
    if not isinstance(markers, list) or not markers:
        return None
    if not all(isinstance(marker, str) and marker.strip() for marker in markers):
        raise ValueError("invalid partnership drift markers")
    return tuple(markers)


GENERIC_SOURCES = {
    "hubspot-affiliate-program": {
        "partner_model": "Affiliate partners promote HubSpot through content, links and referrals.",
        "commission_basis": "Commission and eligibility terms are governed by the current HubSpot Affiliate Program agreement.",
    },
    "microsoft-csp-reseller": {
        "partner_model": "The Microsoft Cloud Solution Provider program enables partners to sell and manage Microsoft cloud services.",
        "commission_basis": "Pricing, incentives and settlement depend on the CSP authorization and partner agreements.",
    },
    "aws-marketplace-channel": {
        "partner_model": "AWS Marketplace Channel connects independent software vendors and Channel Partners for resale and co-selling.",
        "commission_basis": "Private-offer pricing, payment schedules and partner economics follow the AWS Marketplace agreements.",
    },
    "shopify-partner-distribution": {
        "partner_model": "Shopify Partners build and distribute apps, themes, stores and services for merchants.",
        "commission_basis": "Partner earnings, referrals and revenue shares follow Shopify's current partner terms.",
    },
    "apple-mfi-licensing": {
        "partner_model": "The MFi Program licenses Apple technologies and specifications for electronic accessories.",
        "commission_basis": "Licensing, certification, component and commercial terms are governed by the MFi agreement.",
    },
}


def normalize(raw, source, checked_at):
    required = required_markers(source)
    if required is None or (source["id"] != "stripe-partner-ecosystem" and source["id"] not in GENERIC_SOURCES):
        raise ValueError("unknown partnership source")
    parser = Text()
    parser.feed(raw.decode("utf-8"))
    text = " ".join(" ".join(parser.parts).split())
    folded = text.casefold()
    if not all(marker.casefold() in folded for marker in required):
        raise ValueError("partnership source drift or challenge page")
    if source["id"] == "stripe-partner-ecosystem":
        partner_model = "Services, SaaS platform and technology partner tracks are described on the public page."
        commission_basis = (
            "Recurring revenue, monetization and commercial terms are track-specific and not inferred here."
        )
    else:
        partner_model = GENERIC_SOURCES[source["id"]]["partner_model"]
        commission_basis = GENERIC_SOURCES[source["id"]]["commission_basis"]
    item = {
        "id": source["id"],
        "title": source["title"],
        "category": source["category"],
        "source_url": source["source_url"],
        "provider": source["provider"],
        "status": "unknown",
        "deadline": {"kind": "unknown", "at": None},
        "eligible_countries": ["GLOBAL"],
        "eligibility_text": source["eligibility_text"],
        "value": {"kind": "variable", "amount": None, "currency": None, "guaranteed": False},
        "cost": {"fee_amount": None, "currency": None, "auto_renewal": None, "notes": source["cost_notes"]},
        "terms": {
            "partner_model": partner_model,
            "commission_basis": commission_basis,
            "exclusivity_required": None,
            "settlement_terms": "Review the current partner agreement and application terms before joining.",
        },
        "related_records": [],
        "provenance": {
            "evidence_kind": "captured",
            "source_id": source["id"],
            "source_record_id": source["id"],
            "checked_at": checked_at,
            "raw_object_key": None,
            "bronze_manifest_key": None,
        },
    }
    return {
        "schema_version": source["schema_version"],
        "source": source["product"],
        "retrieved_at": checked_at,
        "data_status": "live",
        "items": [item],
    }


def source_config(source_id=None):
    if source_id is None:
        return resource("source.json")
    if not re.fullmatch(r"[a-z0-9-]+", source_id):
        raise ValueError("invalid source id")
    base = resource("source.json")
    if base["id"] == source_id:
        return base
    try:
        return resource("source-" + source_id + ".json")
    except FileNotFoundError:
        raise ValueError("unknown source id") from None


def main(argv=None):
    selector = argparse.ArgumentParser(add_help=False)
    selector.add_argument("--source-id")
    selected, remaining = selector.parse_known_args(argv)
    root = os.environ.get("SOLO_DATA_LAKE_ROOT")
    if not root:
        print("Set SOLO_DATA_LAKE_ROOT to the local shared capture/lake runtime.", file=sys.stderr)
        return 2
    runtime = Path(root).resolve() / "infra/scripts"
    if not (runtime / "discovery/capture_runtime.py").is_file():
        print("Shared discovery runtime is unavailable.", file=sys.stderr)
        return 2
    sys.path.insert(0, str(runtime))
    from discovery.capture_runtime import VERSION, run

    if VERSION != 1:
        raise RuntimeError("unsupported shared capture runtime")
    source = source_config(selected.source_id)
    sentry = init_sentry(source["id"])
    return report_exit(sentry, source["id"], run(source, normalize, validate, remaining))


if __name__ == "__main__":
    raise SystemExit(main())
