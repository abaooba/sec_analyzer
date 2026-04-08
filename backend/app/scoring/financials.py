from frontend.app.metrics import compute_basic_snapshot


CATEGORY_CAP = 20
TOTAL_CAP = 100


def clamp_score(value: float, low: float = 0, high: float = CATEGORY_CAP) -> float:
    return max(low, min(round(value, 2), high))


def score_profitability(snapshot: dict) -> tuple[float, list[str]]:
    notes = []
    score = 0

    operating_margin = snapshot.get("operating_margin")
    net_income = snapshot.get("net_income")

    if operating_margin is None:
        notes.append("Operating margin unavailable.")
    else:
        if operating_margin >= 0.30:
            score += 20
            notes.append("Very strong operating margin.")
        elif operating_margin >= 0.20:
            score += 16
            notes.append("Strong operating margin.")
        elif operating_margin >= 0.10:
            score += 10
            notes.append("Moderate operating margin.")
        elif operating_margin > 0:
            score += 5
            notes.append("Positive but weak operating margin.")
        else:
            notes.append("Negative or zero operating margin.")

    if net_income is not None and net_income > 0:
        notes.append("Company is profitable on a net income basis.")
    elif net_income is not None:
        notes.append("Company is not profitable on a net income basis.")

    return clamp_score(score), notes


def score_cash_generation(snapshot: dict) -> tuple[float, list[str]]:
    notes = []
    score = 0

    operating_cash_flow = snapshot.get("operating_cash_flow")
    free_cash_flow = snapshot.get("free_cash_flow_proxy")
    revenue = snapshot.get("revenue")

    if operating_cash_flow is not None and operating_cash_flow > 0:
        score += 8
        notes.append("Positive operating cash flow.")
    else:
        notes.append("Operating cash flow is weak or unavailable.")

    if free_cash_flow is not None and free_cash_flow > 0:
        score += 8
        notes.append("Positive free cash flow proxy.")
    else:
        notes.append("Free cash flow proxy is weak or unavailable.")

    if free_cash_flow is not None and revenue not in (None, 0):
        fcf_margin = free_cash_flow / revenue
        if fcf_margin >= 0.20:
            score += 4
            notes.append("Very strong free cash flow margin.")
        elif fcf_margin >= 0.10:
            score += 3
            notes.append("Strong free cash flow margin.")
        elif fcf_margin > 0:
            score += 2
            notes.append("Positive free cash flow margin.")
        else:
            notes.append("Weak free cash flow margin.")

    return clamp_score(score), notes


def score_leverage(snapshot: dict) -> tuple[float, list[str]]:
    notes = []
    score = 0

    debt = snapshot.get("long_term_debt")
    equity = snapshot.get("equity")
    assets = snapshot.get("assets")

    if debt is None:
        notes.append("Debt data unavailable.")
        return clamp_score(score), notes

    if equity not in (None, 0):
        debt_to_equity = debt / equity
        if debt_to_equity < 0.5:
            score += 20
            notes.append("Low debt relative to equity.")
        elif debt_to_equity < 1.0:
            score += 15
            notes.append("Manageable debt relative to equity.")
        elif debt_to_equity < 2.0:
            score += 10
            notes.append("Elevated debt relative to equity.")
        else:
            score += 4
            notes.append("High debt relative to equity.")
    elif assets not in (None, 0):
        debt_to_assets = debt / assets
        if debt_to_assets < 0.2:
            score += 16
            notes.append("Low debt relative to assets.")
        elif debt_to_assets < 0.4:
            score += 10
            notes.append("Moderate debt relative to assets.")
        else:
            score += 4
            notes.append("High debt relative to assets.")
    else:
        notes.append("Could not compute leverage ratio.")

    return clamp_score(score), notes


def score_balance_sheet_strength(snapshot: dict) -> tuple[float, list[str]]:
    notes = []
    score = 0

    assets = snapshot.get("assets")
    liabilities = snapshot.get("liabilities")
    equity = snapshot.get("equity")

    if assets in (None, 0) or liabilities is None:
        notes.append("Balance sheet data unavailable.")
        return clamp_score(score), notes

    liability_ratio = liabilities / assets

    if liability_ratio < 0.50:
        score += 20
        notes.append("Very strong balance sheet.")
    elif liability_ratio < 0.70:
        score += 15
        notes.append("Strong balance sheet.")
    elif liability_ratio < 0.85:
        score += 9
        notes.append("Moderate balance sheet strength.")
    else:
        score += 4
        notes.append("Liabilities are heavy relative to assets.")

    if equity is not None and equity > 0:
        notes.append("Company has positive equity.")
    elif equity is not None:
        notes.append("Company has weak or negative equity.")

    return clamp_score(score), notes


def score_capital_efficiency(snapshot: dict) -> tuple[float, list[str]]:
    notes = []
    score = 0

    roe_proxy = snapshot.get("roe_proxy")

    if roe_proxy is None:
        notes.append("ROE proxy unavailable.")
        return clamp_score(score), notes

    if roe_proxy >= 0.25:
        score += 20
        notes.append("Very high capital efficiency.")
    elif roe_proxy >= 0.15:
        score += 15
        notes.append("Strong capital efficiency.")
    elif roe_proxy >= 0.08:
        score += 10
        notes.append("Moderate capital efficiency.")
    elif roe_proxy > 0:
        score += 5
        notes.append("Positive but weak capital efficiency.")
    else:
        notes.append("Negative or zero capital efficiency.")

    return clamp_score(score), notes


def score_financial_quality(cik: str) -> dict:
    snapshot = compute_basic_snapshot(cik)

    profitability_score, profitability_notes = score_profitability(snapshot)
    cash_score, cash_notes = score_cash_generation(snapshot)
    leverage_score, leverage_notes = score_leverage(snapshot)
    balance_sheet_score, balance_sheet_notes = score_balance_sheet_strength(snapshot)
    capital_efficiency_score, capital_efficiency_notes = score_capital_efficiency(snapshot)

    category_scores = {
        "profitability": profitability_score,
        "cash_generation": cash_score,
        "leverage": leverage_score,
        "balance_sheet_strength": balance_sheet_score,
        "capital_efficiency": capital_efficiency_score,
    }

    total_score = round(sum(category_scores.values()), 2)
    total_score = min(total_score, TOTAL_CAP)

    notes = {
        "profitability": profitability_notes,
        "cash_generation": cash_notes,
        "leverage": leverage_notes,
        "balance_sheet_strength": balance_sheet_notes,
        "capital_efficiency": capital_efficiency_notes,
    }

    return {
        "total_financial_score": total_score,
        "category_scores": category_scores,
        "metrics_used": snapshot,
        "notes": notes,
    }