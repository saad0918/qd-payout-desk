import pytest
from app.rules import decide, AUTO_LIMIT

def test_within_limit_pays():            assert decide(200, False).action == "pay"
def test_one_rupee_over_goes_to_ops():   assert decide(201, False).action == "approval"
def test_second_auto_today_goes_to_ops(): assert decide(10, True).action == "approval"
def test_big_amount_always_ops():        assert decide(425, False).action == "approval" and decide(425, True).action == "approval"
@pytest.mark.parametrize("bad", [0, -5])
def test_never_pays_zero_or_negative(bad):
    with pytest.raises(ValueError): decide(bad, False)
def test_limit_value():                  assert AUTO_LIMIT == 200
