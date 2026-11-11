from typing import Any


def build_result(
    decision: str,
    risk_score: int,
    reason_codes: list[str],
    explanation: str,
    policy_version: int,
) -> dict[str, Any]:
    if risk_score < 30:
        risk_level = "LOW"
    elif risk_score < 70:
        risk_level = "MEDIUM"
    else:
        risk_level = "HIGH"

    return {
        "decision": decision,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "approval_required": decision == "REVIEW",
        "reason_codes": reason_codes,
        "explanation": explanation,
        "policy_version": policy_version,
    }


def evaluate(
    payment_intent,
    policy,
    merchant_trust: dict[str, Any],
) -> dict[str, Any]:
    if merchant_trust["decision"] == "BLOCK":
        return build_result(
            decision="BLOCK",
            risk_score=100,
            reason_codes=[
                "MERCHANT_TRUST_BLOCK",
                *merchant_trust["reason_codes"],
            ],
            explanation=(
                "Guardian merchant verification "
                "blocked this merchant."
            ),
            policy_version=policy.version,
        )

    if (
        payment_intent.amount
        > float(policy.single_transaction_limit)
    ):
        return build_result(
            decision="BLOCK",
            risk_score=95,
            reason_codes=[
                "HARD_LIMIT_EXCEEDED"
            ],
            explanation=(
                "Amount exceeds the hard limit."
            ),
            policy_version=policy.version,
        )

    merchant_category = (
        payment_intent
        .merchant
        .category
        .strip()
        .upper()
    )

    blocked_categories = {
        category.strip().upper()
        for category in policy.blocked_categories
    }

    if merchant_category in blocked_categories:
        return build_result(
            decision="BLOCK",
            risk_score=95,
            reason_codes=[
                "BLOCKED_CATEGORY"
            ],
            explanation=(
                f"Category {merchant_category} "
                "is blocked."
            ),
            policy_version=policy.version,
        )

    if (
        payment_intent.purchase_type
        == "SUBSCRIPTION"
        and not policy.subscriptions_allowed
    ):
        return build_result(
            decision="BLOCK",
            risk_score=90,
            reason_codes=[
                "SUBSCRIPTION_PROHIBITED"
            ],
            explanation=(
                "Subscriptions are disabled."
            ),
            policy_version=policy.version,
        )

    risk_score = 10
    reason_codes: list[str] = []

    if merchant_trust["decision"] == "REVIEW":
        risk_score += 30

        reason_codes.append(
            "MERCHANT_TRUST_REVIEW"
        )

        reason_codes.extend(
            merchant_trust["reason_codes"]
        )

    if (
        payment_intent.amount
        >= float(policy.approval_threshold)
    ):
        risk_score += 25

        reason_codes.append(
            "ABOVE_APPROVAL_THRESHOLD"
        )

    if reason_codes:
        return build_result(
            decision="REVIEW",
            risk_score=min(
                risk_score,
                69,
            ),
            reason_codes=sorted(
                set(reason_codes)
            ),
            explanation=(
                "Human approval is required."
            ),
            policy_version=policy.version,
        )

    return build_result(
        decision="ALLOW",
        risk_score=risk_score,
        reason_codes=[],
        explanation=(
            "Merchant and purchase are "
            "within policy."
        ),
        policy_version=policy.version,
    )