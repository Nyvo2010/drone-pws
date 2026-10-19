"""Haak voor LATER autonoom besturen. Nu bewust een stub.

Contract voor de toekomst (nu al vastgelegd, zodat er straks niets hoeft
te breken):
- Input: een State (alleen lezen!).
- Output: dict {"action": ..., "reason": ...} of None (= geen advies).
- De server ROEPT DIT NU NOOIT AAN (autonomy_enabled=False).
- Ooit: echte regelaar implementeert suggest_action() met dezelfde
  signatuur; commando's (pitch/roll/yaw/throttle) gaan via de FC-link van
  de teamgenoot — deze module stuurt nooit direct hardware aan.

Waarom nu al? Zodat perceptie (pipeline), staat (state) en besturing
nooit door elkaar groeien: de naad ligt er al vóór hij nodig is.
"""


def suggest_action(state):
    """Geef één vliegadvies op basis van de staat, of None.

    Huidig gedrag: altijd None + uitleg, want autonomie staat uit.
    Later voorbeeld: {"action": "hold_above", "target": {...},
    "reason": "heetste brand centreren"}.
    """
    _ = state  # nog ongebruikt — stub, zie module-docstring
    return {
        "action": "hold",
        "reason": "autonomie uitgeschakeld (stub) — mens vliegt",
        "enabled": False,
    }
