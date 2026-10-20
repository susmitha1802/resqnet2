"""
ResQNet — Emergency Priority Prediction
"""


def predict_priority(request_type: str, number_of_people: int) -> str:
    """
    Rule-based emergency priority classification.

    Returns:
        'High'   — Rescue / Medicine requests, or >10 people affected
        'Medium' — Food / Water shortages
        'Low'    — Shelter or general assistance
    """
    if request_type in ('Rescue', 'Medicine') or number_of_people > 10:
        return 'High'
    elif request_type in ('Food', 'Water'):
        return 'Medium'
    return 'Low'
