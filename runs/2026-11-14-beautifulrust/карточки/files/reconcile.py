def reconcile(transactions, opening_balance):
    balance = opening_balance
    for t in transactions:
        if t["type"] == "debit":
            balance -= t["amount"]
        elif t["type"] == "credit":
            balance += t["amount"]
        else:
            raise ValueError(f"unknown type: {t['type']}")
    return round(balance, 2)
