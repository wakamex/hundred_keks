# %%
import contextlib
import os
import time
from decimal import ROUND_HALF_DOWN, ROUND_HALF_UP, Decimal, getcontext

from dotenv import load_dotenv

from hundred_x.client import HundredXClient
from hundred_x.enums import Environment, OrderSide, OrderType, TimeInForce

load_dotenv()

# %%
# constants
getcontext().prec = 100
de18 = Decimal(1e18)
d01 = Decimal("0.1")
d02 = Decimal("0.2")
d05 = Decimal("0.5")
d04 = Decimal("0.4")
d0 = Decimal("0")
d1 = Decimal("1")
d2 = Decimal("2")
LAY_MULTIPLE = False

# %%
assert "PRIVATE_KEY" in os.environ, "PRIVATE_KEY not found in .env"

opts = {
    "SYMBOL": "ethperp",
    "SUBACCOUNT_ID": 0,
    "DURATION": 100*1000,  #100 seconds
    "MYSIZE": Decimal('0.01'),
    "MAXSIZE": 1,
    "n_width": 0,
    "avg_width": 0,
    "n_size": 0,
    "avg_size": 0,
    "bid_size": 0,
    "ask_size": 0,
    "start_balance": 0,
    "start_time": 0,
    "dollars_per_hour": 0,
    "mins_spent": 0,
}
client = HundredXClient(env=Environment.PROD, private_key=os.environ.get("PRIVATE_KEY"), subaccount_id=opts["SUBACCOUNT_ID"])

opts["PUBLIC_KEY"] = client.web3.eth.account.from_key(os.environ.get("PRIVATE_KEY")).address
print(f"{opts['PUBLIC_KEY']=}")

products = client.list_products()
print(f"{opts['SYMBOL']=}")
opts["PRODUCT_ID"], opts["INCREMENT"] = next(((product["id"],product["increment"]) for product in products if product["symbol"] == opts["SYMBOL"]),None)
assert isinstance(opts["PRODUCT_ID"], int)
print(f"{opts['PRODUCT_ID']=}")
opts["INCREMENT"] = Decimal(opts["INCREMENT"])/de18
print(f"{opts['INCREMENT']=}")

# %%
client.login()
session_status = client.get_session_status()
print(f"{session_status=}")

# %%
def error(message: str):
    print(message)
    with open("errors.log", "a") as f:
        f.write(f"{time.ctime()}: {message}\n")

# %%
def trade(price, size, is_buy, opts, id_to_cancel=None, initial_delay=0.1, multiplier=1.5, max_delay=10):
    if price.is_nan():
        print("tried to trade with NaN, returning")
        return None, None
    cancel_order = {
        "subaccount_id": opts["SUBACCOUNT_ID"],
        "product_id": opts["PRODUCT_ID"],
        "quantity": size,
        "price": float(price),
        "side": OrderSide.BUY if is_buy else OrderSide.SELL,
        "duration": opts["DURATION"]
    }
    new_order = cancel_order.copy()
    new_order["order_type"] = OrderType.LIMIT_MAKER
    new_order["time_in_force"] = TimeInForce.GTC
    attempt = 1
    while True:
        delay = initial_delay * multiplier**attempt
        try:
            if id_to_cancel is None:
                order_result = client.create_order(**new_order)
            else:
                try:
                    order_result = client.cancel_and_replace_order(**cancel_order, order_id_to_cancel=id_to_cancel)
                except Exception as exc:
                    if "order to cancel not found" in str(exc):
                        order_result = client.create_order(**new_order)
                    else:
                        raise exc
            opts["n_size"] = opts["n_size"] + 1
            opts["avg_size"] = (opts["avg_size"] * (opts["n_size"]-1) + size) / opts["n_size"]
            return order_result["id"]
        except Exception as exc:
            error(
                f"failed to {'submit new' if id_to_cancel is None else 'update'} {'bid' if is_buy else 'ask'}: {exc=}"
                f" bids={opts['depth']['bids']}"
                f" asks={opts['depth']['asks']}"
            )
            if "limit" not in str(exc):
                return None
            time.sleep(delay)
            attempt += 1

def bid(price, size, opts, id_to_cancel=None):
    return trade(price=price, size=size, is_buy=True, opts=opts, id_to_cancel=id_to_cancel)
def ask(price, size, opts, id_to_cancel=None):
    return trade(price=price, size=size, is_buy=False, opts=opts, id_to_cancel=id_to_cancel)
def cancel(opts, id_to_cancel):
    with contextlib.suppress(Exception):
        client.cancel_order(subaccount_id=opts["SUBACCOUNT_ID"], product_id=opts["PRODUCT_ID"], order_id=id_to_cancel)

def get_thing(thing: str, initial_delay=0.1, multiplier=1.5, max_delay=10):
    attempt = 1
    while True:
        delay = min(max_delay, initial_delay * multiplier**attempt)
        try:
            if thing == "balance":
                return Decimal(client.get_spot_balances()[0]["quantity"])/de18
            elif thing == "depth":
                return client.get_depth(opts["SYMBOL"], granularity=5, limit=5)
            elif thing == "position":
                return client.get_position()
        except Exception as exc:
            error(f"failed to get {thing} {attempt=}: {exc=}")
            attempt += 1
            time.sleep(delay)

def get_balance(opts) -> Decimal:
    balance = get_thing("balance")
    if opts["start_time"] == 0:
        opts["start_balance"] = balance
        opts["start_time"] = time.time()
    else:
        opts["mins_spent"] = Decimal((time.time() - opts["start_time"]) / 60)
        opts["dollars_per_hour"] = (balance - opts["start_balance"]) * 60 / opts["mins_spent"]
    return balance

def get_depth() -> dict:
    depth_result = get_thing("depth")
    assert isinstance(depth_result, dict)
    return depth_result

def get_position() -> list:
    position = get_thing("position")
    assert isinstance(position, list)
    return position

def update_my_prices(opts, debug=False):
    start_time = time.time()
    depth = get_depth()
    opts["depth"] = depth

    best_bid = Decimal(depth["bids"][0][0])/de18
    best_ask = Decimal(depth["asks"][0][0])/de18
    best_big_bid = Decimal('NaN')
    for bid in depth["bids"]:
        if Decimal(bid[1])/de18 > 5:
            best_big_bid = Decimal(bid[0])/de18
            break
    best_big_ask = Decimal('NaN')
    for ask in depth["asks"]:
        if Decimal(ask[1])/de18 > 5:
            best_big_ask = Decimal(ask[0])/de18
            break
    mid = (best_ask + best_bid) / d2

    # my_bid = mid - d05 if best_big_bid.is_nan() else min(best_big_bid + d01, mid - d02)
    # my_ask = mid + d05 if best_big_ask.is_nan() else max(best_big_ask - d01, mid + d02)
    # my_bid = mid - d05 if best_big_bid.is_nan() else best_big_bid
    # my_ask = mid + d05 if best_big_ask.is_nan() else best_big_ask
    my_bid = mid - d04 if best_big_bid.is_nan() else best_big_bid
    my_ask = mid + d04 if best_big_ask.is_nan() else best_big_ask
    balance = get_balance(opts)
    position_risk = get_position()
    pos = Decimal(position_risk[0]["quantity"])/de18 if len(position_risk) > 0 else d0
    margin = Decimal(position_risk[0]["margin"])/de18 if len(position_risk) > 0 else d0
    usage = margin / balance

    if pos > opts["MAXSIZE"]:  # we are long, we want to sell
        my_bid = Decimal('NaN')
    elif pos < -opts["MAXSIZE"]:  # we are short, we want to buy
        my_ask = Decimal('NaN')
    if pos > 0:  # we are long, we want to sell
        my_ask = best_ask
    elif pos < 0:  # we are short, we want to buy
        my_bid = best_bid
    width = my_ask - my_bid
    if not width.is_nan():
        opts["n_width"] = opts["n_width"] + 1
        opts["avg_width"] = (opts["avg_width"] * (opts["n_width"]-1) + width) / opts["n_width"]
    print(
        f"pos={pos:5.2f}({usage:.1%})"
        f" prices [{my_bid:6.1f}, {my_ask:6.1f}"
        # f", {my_bid-mid:+3.2f}, {my_ask-mid:+3.2f}"
        # f", {bid_bias:+3.2f}, {ask_bias:+3.2f}"
        f"] in {time.time() - start_time:.3f}s"
        f", avg_size={opts['avg_size']:.3f}"
        f", avg_width={opts['avg_width']:.3f}"
        f", dollars_per_hour={opts['dollars_per_hour']:.2f}"
        f" ({opts['mins_spent']:,.1f} mins)"
        )
    # quantize at the very end
    my_bid = my_bid.quantize(opts["INCREMENT"], rounding=ROUND_HALF_DOWN)
    my_ask = my_ask.quantize(opts["INCREMENT"], rounding=ROUND_HALF_UP)
    return my_bid, my_ask, mid, pos, usage, balance

def orders(symbol: str):
    try:
        return client.get_open_orders(symbol)
    except Exception as exc:
        error(f"failed to get orders: {exc=}")
        return []

# %%
my_bid = my_ask = bid_id = bid_id2 = bid_id3 = ask_id = ask_id2 = ask_id3 = None
pos = 0
client.cancel_all_orders(opts["SUBACCOUNT_ID"], opts["PRODUCT_ID"])
while True:
    open_orders = orders(opts["SYMBOL"])
    open_bid_ids, open_ask_ids, open_bid_prices, open_ask_prices = [], [], [], []
    for o in open_orders:
        if isinstance(o, dict):
            if o.get("isBuy") == True:
                open_bid_ids.append(o["id"])
                open_bid_prices.append(Decimal(o["price"]) / de18)
            elif o.get("isBuy") == False:
                open_ask_ids.append(o["id"])
                open_ask_prices.append(Decimal(o["price"]) / de18)
    if bid_id not in open_bid_ids:  # reset bid
        bid_id = my_bid = None
    if ask_id not in open_ask_ids:  # reset ask
        ask_id = my_ask = None
    if LAY_MULTIPLE:
        bid_id2 = bid_id2 if bid_id2 in open_bid_ids else None
        bid_id3 = bid_id3 if bid_id3 in open_bid_ids else None
        ask_id2 = ask_id2 if ask_id2 in open_ask_ids else None
        ask_id3 = ask_id3 if ask_id3 in open_ask_ids else None
    last_bid, last_ask = my_bid, my_ask
    my_bid, my_ask, mid, new_pos, usage, balance = update_my_prices(opts, debug=False)
    if new_pos is not None and not new_pos.is_nan():
        pos = new_pos
    start_time = time.time()
    updated = 0
    
    if my_bid is not None and not my_bid.is_nan():
        if pos < 0:  # we are short, so try to buy the whole thing
            if my_bid not in open_bid_prices:
                bid_id = bid(price=my_bid, size=-pos, opts=opts, id_to_cancel=bid_id)
                updated += 1
            # cancel orphaned orders
            for idx, open_bid_price in enumerate(open_bid_prices):
                if open_bid_price not in [my_bid]:
                    cancel(opts, open_bid_ids[idx])
        else:
            if my_bid not in open_bid_prices:
                bid_id = bid(price=my_bid, size=opts["MYSIZE"], opts=opts, id_to_cancel=bid_id)
                updated += 1
            if LAY_MULTIPLE:  # we lay multiple bids
                if (my_bid-opts["INCREMENT"]) not in open_bid_prices:
                    bid_id2 = bid(price=my_bid-opts["INCREMENT"], size=opts["MYSIZE"], opts=opts, id_to_cancel=bid_id2)
                    updated += 1
                if (my_bid-2*opts["INCREMENT"]) not in open_bid_prices:
                    bid_id3 = bid(price=my_bid-2*opts["INCREMENT"], size=opts["MYSIZE"], opts=opts, id_to_cancel=bid_id3)
                    updated += 1
            # cancel orphaned orders
            if LAY_MULTIPLE:
                for idx, open_bid_price in enumerate(open_bid_prices):
                    if open_bid_price not in [my_bid, my_bid-opts["INCREMENT"], my_bid-2*opts["INCREMENT"]]:
                        cancel(opts, open_bid_ids[idx])
            else:
                for idx, open_bid_price in enumerate(open_bid_prices):
                    if open_bid_price not in [my_bid]:
                        cancel(opts, open_bid_ids[idx])

    if my_ask is not None and not my_ask.is_nan():
        if pos > 0:  # we are long, so try to sell the whole thing
            if my_ask not in open_ask_prices:
                ask_id = ask(price=my_ask, size=pos, opts=opts, id_to_cancel=ask_id)
                updated += 1
                # cancel orphaned orders
                for idx, open_ask_price in enumerate(open_ask_prices):
                    if open_ask_price not in [my_ask]:
                        cancel(opts, open_ask_ids[idx])
        else:
            if my_ask not in open_ask_prices:
                ask_id = ask(price=my_ask, size=opts["MYSIZE"], opts=opts, id_to_cancel=ask_id)
                updated += 1
            if LAY_MULTIPLE:  # we lay multiple asks
                if (my_ask+opts["INCREMENT"]) not in open_ask_prices:
                    ask_id2 = ask(price=my_ask+opts["INCREMENT"], size=opts["MYSIZE"], opts=opts, id_to_cancel=ask_id2)
                    updated += 1
                if (my_ask+2*opts["INCREMENT"]) not in open_ask_prices:
                    ask_id3 = ask(price=my_ask+2*opts["INCREMENT"], size=opts["MYSIZE"], opts=opts, id_to_cancel=ask_id3)
                    updated += 1
            # cancel orphaned orders
            if LAY_MULTIPLE:
                for idx, open_ask_price in enumerate(open_ask_prices):
                    if open_ask_price not in [my_ask, my_ask+opts["INCREMENT"], my_ask+2*opts["INCREMENT"]]:
                        cancel(opts, open_ask_ids[idx])
            else:
                for idx, open_ask_price in enumerate(open_ask_prices):
                    if open_ask_price not in [my_ask]:
                        cancel(opts, open_ask_ids[idx])
    if updated > 0:
        print(f"updated {updated} orders in: {time.time() - start_time:.3f}s")

# %%
# get price
_, _, _, _ = update_my_prices(debug=True)

