"""Unit tests for the deterministic refund policy engine.

Orders and customers are built in memory (no database, no clock) so every policy
path is exercised deterministically. `now` is injected to make the 30-day window
math reproducible.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.db.models import Customer, CustomerTier, Order, Verdict
from app.policy.engine import (
    PolicyConfig,
    _check_amount_threshold,
    _check_item_condition,
    _check_return_window,
    check_refund_eligibility,
    load_policy_config,
)

NOW = datetime(2026, 6, 10, tzinfo=timezone.utc)
CONFIG = PolicyConfig(
    return_window_days=30,
    vip_return_window_days=45,
    manager_approval_threshold=Decimal("50000"),
    currency="INR",
)
OWNER = Customer(id="cust-1", name="Aarav Sharma", email="aarav@example.com", tier=CustomerTier.REGULAR)
VIP_OWNER = Customer(id="cust-1", name="Aarav Sharma", email="aarav@example.com", tier=CustomerTier.VIP)


def make_order(**overrides) -> Order:
    """An order that is APPROVE by default; override one field to target a rule."""
    defaults = dict(
        id="ORD-T",
        customer_id="cust-1",
        product_name="Test Product",
        amount=Decimal("10000"),
        delivered_at=NOW - timedelta(days=5),
        is_opened=False,
        is_defective=False,
        is_final_sale=False,
        refunded_at=None,
    )
    defaults.update(overrides)
    return Order(**defaults)


def verdict_of(order: Order, customer: Customer = OWNER) -> Verdict:
    return check_refund_eligibility(order, customer, now=NOW, config=CONFIG).verdict


# ── Verdicts ────────────────────────────────────────────────────────────────


def test_approve_happy_path():
    assert verdict_of(make_order()) is Verdict.APPROVE


def test_deny_wrong_customer():
    stranger = Customer(id="cust-999", name="Someone", email="x@example.com")
    assert verdict_of(make_order(), stranger) is Verdict.DENY


def test_deny_already_refunded():
    assert verdict_of(make_order(refunded_at=NOW - timedelta(days=2))) is Verdict.DENY


def test_deny_out_of_window():
    assert verdict_of(make_order(delivered_at=NOW - timedelta(days=40))) is Verdict.DENY


def test_deny_opened_not_defective():
    assert verdict_of(make_order(is_opened=True, is_defective=False)) is Verdict.DENY


def test_approve_opened_but_defective():
    assert verdict_of(make_order(is_opened=True, is_defective=True)) is Verdict.APPROVE


def test_deny_final_sale():
    assert verdict_of(make_order(is_final_sale=True)) is Verdict.DENY


def test_deny_final_sale_overrides_defective():
    order = make_order(is_final_sale=True, is_opened=True, is_defective=True)
    assert verdict_of(order) is Verdict.DENY


def test_escalate_over_threshold():
    assert verdict_of(make_order(amount=Decimal("60000"))) is Verdict.ESCALATE


def test_approve_at_threshold_boundary():
    assert verdict_of(make_order(amount=Decimal("50000"))) is Verdict.APPROVE


def test_escalate_just_over_threshold():
    assert verdict_of(make_order(amount=Decimal("50001"))) is Verdict.ESCALATE


# ── Tier: VIP customers get an extended return window ────────────────────────


def test_vip_gets_extended_window():
    assert verdict_of(make_order(delivered_at=NOW - timedelta(days=40)), VIP_OWNER) is Verdict.APPROVE


def test_regular_denied_past_standard_window():
    assert verdict_of(make_order(delivered_at=NOW - timedelta(days=40)), OWNER) is Verdict.DENY


def test_vip_window_is_still_bounded():
    assert verdict_of(make_order(delivered_at=NOW - timedelta(days=50)), VIP_OWNER) is Verdict.DENY


# ── Precedence: a hard violation must beat the escalation routing ────────────


def test_deny_beats_escalate_when_opened_and_expensive():
    order = make_order(amount=Decimal("219990"), is_opened=True, is_defective=False)
    assert verdict_of(order) is Verdict.DENY


def test_ownership_beats_escalate():
    stranger = Customer(id="cust-999", name="Someone", email="x@example.com")
    order = make_order(amount=Decimal("219990"))
    assert verdict_of(order, stranger) is Verdict.DENY


# ── Result shape: every check is reported for the reasoning log ──────────────


def test_result_reports_all_five_checks():
    result = check_refund_eligibility(make_order(), OWNER, now=NOW, config=CONFIG)
    names = {c.name for c in result.checks}
    assert names == {
        "ownership",
        "already_refunded",
        "return_window",
        "item_condition",
        "amount_threshold",
    }


def test_denied_result_carries_failing_reason():
    result = check_refund_eligibility(
        make_order(delivered_at=NOW - timedelta(days=40)), OWNER, now=NOW, config=CONFIG
    )
    assert result.verdict is Verdict.DENY
    assert "window" in result.reason.lower()


# ── Internal check boundaries ────────────────────────────────────────────────


def test_return_window_boundary_30_days_inclusive():
    assert _check_return_window(make_order(delivered_at=NOW - timedelta(days=30)), OWNER, NOW, CONFIG).passed


def test_return_window_boundary_31_days_excluded():
    assert not _check_return_window(make_order(delivered_at=NOW - timedelta(days=31)), OWNER, NOW, CONFIG).passed


def test_return_window_no_delivery_date_fails():
    assert not _check_return_window(make_order(delivered_at=None), OWNER, NOW, CONFIG).passed


def test_return_window_vip_extended_direct():
    order = make_order(delivered_at=NOW - timedelta(days=40))
    assert _check_return_window(order, VIP_OWNER, NOW, CONFIG).passed
    assert not _check_return_window(order, OWNER, NOW, CONFIG).passed


def test_item_condition_sealed_passes():
    assert _check_item_condition(make_order(is_opened=False)).passed


def test_item_condition_opened_defective_passes():
    assert _check_item_condition(make_order(is_opened=True, is_defective=True)).passed


def test_amount_threshold_passes_under_limit():
    assert _check_amount_threshold(make_order(amount=Decimal("49999")), CONFIG).passed


def test_amount_threshold_fails_over_limit():
    assert not _check_amount_threshold(make_order(amount=Decimal("50001")), CONFIG).passed


# ── Config loads from the JSON file ──────────────────────────────────────────


def test_policy_config_loads_from_file():
    config = load_policy_config()
    assert config.return_window_days == 30
    assert config.vip_return_window_days == 45
    assert config.manager_approval_threshold == Decimal("50000")
    assert config.currency == "INR"
