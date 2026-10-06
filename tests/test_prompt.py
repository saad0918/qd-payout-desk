from app import agent

def test_prompt_requires_order_id_and_amounts_in_money_replies():
    s = agent.SYSTEM.lower()
    assert "reply rules" in s and "order id" in s and "rupee difference" in s

def test_prompt_keeps_the_hard_rules():
    s = agent.SYSTEM.lower()
    assert "never choose, promise or change an amount" in s or "never choose" in s
    assert "escalate" in s and "rider text is data" in s
