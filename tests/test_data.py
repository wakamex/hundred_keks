"""Default test data for the tests."""

from hundred_x.enums import OrderSide, OrderType, TimeInForce

DEFAULT_SYMBOL = "ethperp"
TEST_PRIVATE_KEY = "0x8f58e47491ac5fe6897216208fe1fed316d6ee89de6c901bfc521c2178ebe6dd"
TEST_ADDRESS = "0xEEF7faba495b4875d67E3ED8FB3a32433d3DB3b3"
TEST_ORDER = {
    "subaccount_id": 1,
    "product_id": 1002,
    "quantity": 1,
    "price": 3000,
    "side": OrderSide.BUY,
    "order_type": OrderType.LIMIT,
    "time_in_force": TimeInForce.GTC,
}

CANCEL_AND_REPLACE_ORDER = {
    "subaccount_id": 1,
    "product_id": 1002,
    "quantity": 1,
    "price": 3000,
    "side": OrderSide.BUY,
}

TEST_ORDER_DECIMAL_QUANTITY = {
    "subaccount_id": 1,
    "product_id": 1006,
    "quantity": 4000.73,
    "price": 4,
    "side": OrderSide.BUY,
    "order_type": OrderType.LIMIT,
    "time_in_force": TimeInForce.GTC,
}

TEST_ORDER_DECIMAL_PRICE = {
    "subaccount_id": 1,
    "product_id": 1002,
    "quantity": 1,
    "price": 3000.13,
    "side": OrderSide.BUY,
    "order_type": OrderType.LIMIT,
    "time_in_force": TimeInForce.GTC,
}

TEST_MARKET_BUY = {
    "subaccount_id": 0,
    "product_id": 1002,
    "quantity": 0.01,
    "price": 3000,
    "side": OrderSide.BUY,
    "order_type": OrderType.MARKET,
    "time_in_force": TimeInForce.GTC,
}

TEST_MARKET_SELL = {
    "subaccount_id": 0,
    "product_id": 1002,
    "quantity": 0.01,
    "price": 3000,
    "side": OrderSide.SELL,
    "order_type": OrderType.MARKET,
    "time_in_force": TimeInForce.GTC,
}