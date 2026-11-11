from app.decision_engine import evaluate, PolicyRules
from app.schemas import PaymentIntentCreate

policy=PolicyRules(200,75,{"ELECTRONICS"},{"GAMBLING"},True,False,2)
def intent(amount=40,known=True,purchase_type="ONE_TIME",category="ELECTRONICS"):
 return PaymentIntentCreate(intent_id="i",merchant={"id":"m","name":"Store","category":category,"is_known":known},
 items=[{"sku":"s","name":"Item","quantity":1,"unit_price":amount}],amount=amount,purchase_type=purchase_type)
def test_allow(): assert evaluate(intent(),policy)["decision"]=="ALLOW"
def test_review(): assert evaluate(intent(79.99,False),policy)["decision"]=="REVIEW"
def test_subscription_block(): assert evaluate(intent(purchase_type="SUBSCRIPTION"),policy)["decision"]=="BLOCK"
def test_limit_block(): assert evaluate(intent(201),policy)["reason_codes"]==["HARD_LIMIT_EXCEEDED"]
def test_category_block(): assert evaluate(intent(category="GAMBLING"),policy)["decision"]=="BLOCK"
