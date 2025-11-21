# logic.py

import json
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Tuple


class CalculationError(Exception):
    """Custom exception for calculation errors."""

    pass


def safe_decimal_eval(expression: str) -> Decimal:
    """
    Safely evaluates a string expression and returns it as a Decimal.
    Raises CalculationError for invalid expressions.
    """
    if not expression:
        return Decimal(0)
    try:
        # Using eval with limited scope for simple arithmetic (e.g., "15/2")
        return Decimal(eval(expression, {"__builtins__": None}, {}))
    except Exception:
        raise CalculationError(f"Invalid expression: {expression}")


def load_people_from_file(filepath: str) -> List[str]:
    """
    Loads a list of people from a JSON file.
    Raises FileNotFoundError or json.JSONDecodeError on failure.
    """
    with open(filepath, "r") as f:
        return json.load(f)


def calculate_split_from_items(
    item_prices: Dict[str, float],
    allocations: Dict[str, Dict[str, int]],
    all_people: List[str],
    other_charges: Decimal,
) -> Dict:
    """
    Performs the bill splitting calculation from itemized data.
    """
    person_totals = {p: Decimal(0) for p in all_people}

    for item_id, item_allocations in allocations.items():
        total_shares = sum(item_allocations.values())
        if total_shares == 0:
            continue

        price = Decimal(item_prices[item_id])
        cost_per_share = price / Decimal(total_shares)

        for person, share in item_allocations.items():
            if share > 0:
                person_totals[person] += cost_per_share * Decimal(share)

    subtotal = sum(person_totals.values())

    if subtotal == 0:
        if other_charges > 0:
            num_people = len(all_people)
            if num_people > 0:
                split_other_charges = other_charges / num_people
                final_amounts = {p: split_other_charges for p in all_people}
                is_equal_split = True
            else:
                final_amounts = {}
                is_equal_split = False
        else:
            return {}
    else:
        final_amounts = {p: person_totals[p] for p in all_people}
        is_equal_split = False
        if other_charges > 0:
            for person, total in person_totals.items():
                weight = total / subtotal
                final_amounts[person] += other_charges * Decimal(weight)

    grand_total = subtotal + other_charges

    return {
        "subtotal": subtotal,
        "grand_total": grand_total,
        "final_amounts": list(final_amounts.items()),
        "is_equal_split": is_equal_split,
    }


def calculate_split_bill(
    person_amounts: List[Tuple[str, Decimal]], other_charges: Decimal
) -> Dict:
    """
    Performs the bill splitting calculation.
    (Now a wrapper for calculate_split_from_items for compatibility)
    """
    all_people = [name for name, _ in person_amounts]
    item_prices = {f"item_{i}": amount for i, (_, amount) in enumerate(person_amounts)}
    allocations = {
        f"item_{i}": {name: 1 if amount > 0 else 0 for name, amount in person_amounts}
        for i in range(len(person_amounts))
    }

    # This is a simplified adaptation. The core logic is now in calculate_split_from_items.
    # The original logic for equal splitting when total is 0 is preserved.
    total = sum(amount for _, amount in person_amounts)
    if total == 0:
        if other_charges > 0 and person_amounts:
            num_people = len(person_amounts)
            split_other_charges = other_charges / num_people
            final_amounts = [(name, split_other_charges) for name, _ in person_amounts]
            return {
                "subtotal": Decimal(0),
                "grand_total": other_charges,
                "final_amounts": final_amounts,
                "is_equal_split": True,
            }
        else:
            return {}

    return calculate_split_from_items(item_prices, allocations, all_people, other_charges)
