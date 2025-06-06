"""Wrap the the REST API of the exchange."""

import time
from decimal import Decimal
from typing import Any, List

import requests
from dotenv import load_dotenv
from eip712_structs import make_domain
from eth_account.messages import encode_structured_data
from web3 import Web3
from web3.exceptions import TransactionNotFound

from hundred_x.constants import APIS, CONTRACTS, LOGIN_MESSAGE, REFERRAL_CODE, RPC_URLS, SUCCESS_CODE
from hundred_x.eip_712 import CancelOrder, CancelOrders, LoginMessage, Order, Referral, Withdraw
from hundred_x.enums import ApiType, Environment, OrderSide, OrderType, TimeInForce
from hundred_x.exceptions import ClientError, UserInputValidationError
from hundred_x.utils import from_message_to_payload, get_abi

load_dotenv()

headers = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}


PROTOCOL_ABI = get_abi("protocol")
ERC_20_ABI = get_abi("erc20")
TIMEOUT = 60


class HundredXClient:
    """The 100x client."""

    private_functions: List[str] = [
        "/v1/withdraw",
        "/v1/order",
        "/v1/order/cancel-and-replace",
        "/v1/order",
        "/v1/openOrders",
        "/v1/orders",
        "/v1/balances",
        "/v1/positionRisk",
        "/v1/approved-signers",
        "/v1/session/login",
        "/v1/referral/add-referee",
        "/v1/session/logout",
    ]
    public_functions: List[str] = [
        "/v1/products",
        "/v1/products/{product_symbol}",
        "/v1/trade-history",
        "/v1/time",
        "/v1/uiKlines",
        "/v1/ticker/24hr",
        "/v1/depth",
    ]

    def __init__(
        self,
        env: Environment = Environment.TESTNET,
        private_key: str | None = None,
        subaccount_id: int = 0,
    ):
        """Initialize the client with the given environment."""
        self.env = env
        self.rest_url = APIS[env][ApiType.REST]
        self.websocket_url = APIS[env][ApiType.WEBSOCKET]
        if any([not self.rest_url, not self.websocket_url]):
            raise UserInputValidationError(
                f"Invalid environment: {env} Missing REST or WEBSOCKET URL for the environment."
            )
        self.web3 = Web3(Web3.HTTPProvider(RPC_URLS[env]))
        if private_key:
            self.wallet = self.web3.eth.account.from_key(private_key)
            self.public_key = self.wallet.address
            if subaccount_id < 0 or subaccount_id > 255:
                raise ValueError("Subaccount ID must be a number between 0 and 255.")
            self.subaccount_id = subaccount_id
        self.session_cookie = {}
        self.domain = make_domain(
            name="100x",
            version="0.0.0",
            chainId=CONTRACTS[env]["CHAIN_ID"],
            verifyingContract=CONTRACTS[env]["VERIFYING_CONTRACT"],
        )
        self.set_referral_code()

    def _validate_function(self,endpoint):
        """Check if the endpoint is a private function."""
        if endpoint not in self.private_functions + self.public_functions:
            raise ClientError(f"Invalid endpoint: {endpoint} Not in {self.private_functions + self.public_functions}")
        if endpoint in self.public_functions:
            return True
        if endpoint in self.private_functions:
            if not self.wallet:
                raise UserInputValidationError(
                    f"Private function {endpoint} requires a private key please provide one at initialization."
                )
            return True

    def _current_timestamp(self):
        """Return current timestamp in milliseconds."""
        return int(time.time() * 1000)

    def generate_and_sign_message(self, message_class, **kwargs):
        """Generate and sign a message."""
        message = message_class(**kwargs)
        message = message.to_message(self.domain)
        signable_message = encode_structured_data(message)
        signed = self.wallet.sign_message(signable_message)
        message["message"]["signature"] = signed.signature.hex()
        return message["message"]

    def get_shared_params(self, asset: str | None = None, subaccount_id: int | None = None):
        """Return shared parameters for requests."""
        params = {"account": self.public_key}
        if asset is not None:
            params["asset"] = self.get_contract_address(asset)
        if subaccount_id is not None:
            params["subAccountId"] = subaccount_id
        return params

    def send_message_to_endpoint(self, endpoint: str, method: str, message: dict, authenticated: bool = True):
        """Send a message to an endpoint."""
        if not self._validate_function(endpoint):
            raise ClientError(f"Invalid endpoint: {endpoint}")
        payload = from_message_to_payload(message)
        response = requests.request(
            method,
            self.rest_url + endpoint,
            headers=self.authenticated_headers if authenticated else {},
            json=payload,
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            raise ConnectionError(f"Failed to send message: {response.text} {response.status_code} {self.rest_url} {payload}")
        return response.json()

    def withdraw(self, subaccount_id: int, quantity: int, asset: str = "USDB"):
        """Generate a withdrawal message and sign it."""
        message = self.generate_and_sign_message(
            Withdraw,
            quantity=int(quantity * 1e18),
            nonce=self._current_timestamp(),
            **self.get_shared_params(subaccount_id=subaccount_id, asset=asset),
        )
        return self.send_message_to_endpoint("/v1/withdraw", "POST", message)

    def create_order(
        self,
        subaccount_id: int,
        product_id: int,
        quantity: int,
        price: int,
        side: OrderSide,
        order_type: OrderType,
        time_in_force: TimeInForce,
        nonce: int = 0,
        duration: int = 1000,
    ):
        """Create an order."""
        ts = self._current_timestamp()
        if nonce == 0:
            nonce = ts
        message = self.generate_and_sign_message(
            Order,
            subAccountId=subaccount_id,
            productId=product_id,
            quantity=int(Decimal(str(quantity)) * Decimal(1e18)),
            price=int(Decimal(str(price)) * Decimal(1e18)),
            isBuy=side.value,
            orderType=order_type.value,
            timeInForce=time_in_force.value,
            nonce=nonce,
            expiration0=ts + duration,
            **self.get_shared_params(),
        )
        return self.send_message_to_endpoint("/v1/order", "POST", message)

    def cancel_and_replace_order(
        self,
        subaccount_id: int,
        product_id: int,
        quantity: int,
        price: int,
        side: OrderSide,
        order_id_to_cancel: str,
        nonce: int = 0,
        duration: int = 1000,
    ):
        """Cancel and replace an order."""
        ts = self._current_timestamp()
        if nonce == 0:
            nonce = ts
        _message = self.generate_and_sign_message(
            Order,
            subAccountId=subaccount_id,
            productId=product_id,
            quantity=int(Decimal(str(quantity)) * Decimal(1e18)),
            price=int(Decimal(str(price)) * Decimal(1e18)),
            isBuy=side.value,
            orderType=OrderType.LIMIT_MAKER.value,
            timeInForce=TimeInForce.GTC.value,
            nonce=nonce,
            expiration=ts + duration,
            **self.get_shared_params(),
        )
        message = {
            "newOrder": from_message_to_payload(_message),
            "idToCancel": order_id_to_cancel,
        }
        return self.send_message_to_endpoint("/v1/order/cancel-and-replace", "POST", message)

    def cancel_order(self, subaccount_id: int, product_id: int, order_id: int):
        """Cancel an order."""
        message = self.generate_and_sign_message(
            CancelOrder,
            subAccountId=subaccount_id,
            productId=product_id,
            orderId=order_id,
            **self.get_shared_params(),
        )
        return self.send_message_to_endpoint("/v1/order", "DELETE", message)

    def cancel_all_orders(self, subaccount_id: int, product_id: int):
        """Cancel all orders."""
        message = self.generate_and_sign_message(
            CancelOrders,
            subAccountId=subaccount_id,
            productId=product_id,
            **self.get_shared_params(),
        )
        return self.send_message_to_endpoint("/v1/openOrders", "DELETE", message)

    def create_authenticated_session_with_service(self):
        """Log in and return session cookie."""
        login_payload = self.generate_and_sign_message(
            LoginMessage,
            message=LOGIN_MESSAGE,
            timestamp=self._current_timestamp(),
            **self.get_shared_params(),
        )
        response = self.send_message_to_endpoint("/v1/session/login", "POST", login_payload, authenticated=False)
        self.session_cookie = response.get("value")
        return response

    def list_products(self) -> List[Any]:
        """Get a list of all available products."""
        return requests.get(f"{self.rest_url}/v1/products", timeout=TIMEOUT).json()

    def get_product(self, product_symbol: str) -> Any:
        """Get the details of a specific product."""
        return requests.get(f"{self.rest_url}/v1/products/{product_symbol}", timeout=TIMEOUT).json()

    def get_trade_history(self, symbol: str, lookback: int) -> Any:
        """Get the trade history for a specific product symbol and lookback amount."""
        return requests.get(
            f"{self.rest_url}/v1/trade-history",
            params={"symbol": symbol, "lookback": lookback},
            timeout=TIMEOUT,
        ).json()

    def get_server_time(self) -> Any:
        """Get the server time."""
        return requests.get(f"{self.rest_url}/v1/time", timeout=TIMEOUT).json()

    def get_candlestick(self, symbol: str, **kwargs) -> Any:
        """Get the candlestick data for a specific product."""
        params = {"symbol": symbol}
        for arg in ["interval", "start_time", "end_time", "limit"]:
            var = kwargs.get(arg)
            if var is not None:
                params[arg] = var
        return requests.get(f"{self.rest_url}/v1/uiKlines", params=params, timeout=TIMEOUT).json()

    def get_symbol(self, symbol: str) -> Any:
        """Get the details of a specific symbol."""
        endpoint = f"/v1/ticker/24hr?symbol={symbol}"
        return requests.get(self.rest_url + endpoint, timeout=TIMEOUT).json()[0]

    def get_depth(self, symbol: str, **kwargs) -> Any:
        """Get the depth data for a specific product."""
        params = {"symbol": symbol}
        for arg in ["limit"]:
            var = kwargs.get(arg)
            if var is not None:
                params[arg] = var
        return requests.get(f"{self.rest_url}/v1/depth", params=params, timeout=TIMEOUT).json()

    def login(self):
        """Login to the exchange."""
        response = self.create_authenticated_session_with_service()
        if response is None:
            raise ConnectionError("Failed to login")

    def get_session_status(self):
        """Get the current session status."""
        return requests.get(
            f"{self.rest_url}/v1/session/status",
            headers=self.authenticated_headers,
            timeout=TIMEOUT,
        ).json()

    @property
    def authenticated_headers(self):
        """Get the authenticated headers."""
        return {"cookie": f"connectedAddress={self.session_cookie}"}

    def logout(self):
        """Logout from the exchange."""
        return requests.get(
            f"{self.rest_url}/v1/session/logout",
            headers=self.authenticated_headers,
            timeout=TIMEOUT,
        ).json()

    def get_spot_balances(self):
        """Get the spot balances."""
        return requests.get(
            f"{self.rest_url}/v1/balances",
            headers=self.authenticated_headers,
            params={
                "account": self.public_key,
                "subAccountId": self.subaccount_id,
            },
            timeout=TIMEOUT,
        ).json()

    def get_position(self):
        """Get all positions for the subaccount."""
        return requests.get(
            f"{self.rest_url}/v1/positionRisk",
            headers=self.authenticated_headers,
            params={
                "account": self.public_key,
                "subAccountId": self.subaccount_id,
            },
            timeout=TIMEOUT,
        ).json()

    def get_approved_signers(self):
        """Get the approved signers."""
        return requests.get(
            f"{self.rest_url}/v1/approved-signers",
            headers=self.authenticated_headers,
            params={
                "account": self.public_key,
                "subAccountId": self.subaccount_id,
            },
            timeout=TIMEOUT,
        ).json()

    def get_open_orders(self,symbol: str | None = None):
        """Get the open orders."""
        params = {"account": self.public_key, "subAccountId": self.subaccount_id}
        if symbol is not None:
            params["symbol"] = symbol
        return requests.get(
            f"{self.rest_url}/v1/openOrders",
            headers=self.authenticated_headers,
            params=params,
            timeout=TIMEOUT,
        ).json()

    def get_orders(self, symbol: str | None = None, ids: List[str] | None = None):
        """Get the open orders."""
        params = {"account": self.public_key, "subAccountId": self.subaccount_id}

        if ids is not None:
            params["ids"] = ids
        if symbol is not None:
            params["symbol"] = symbol

        response = requests.get(
            f"{self.rest_url}/v1/orders",
            headers=self.authenticated_headers,
            params=params,
            timeout=TIMEOUT,
        )
        if response.status_code != SUCCESS_CODE:
            raise ConnectionError(
                f"Failed to get orders: {response.text} {response.status_code} " + f"{self.rest_url} {params}"
            )
        return response.json()

    def set_referral_code(self):
        """Ensure sign a referral code."""
        referral_payload = self.generate_and_sign_message(
            Referral,
            code=REFERRAL_CODE,
            **self.get_shared_params(),
        )
        try:
            return self.send_message_to_endpoint("/v1/referral/add-referee", "POST", referral_payload)
        except Exception as exc:
            if "user already referred" in str(exc):
                return
            raise exc

    def deposit(self, subaccount_id: int, quantity: int, asset: str = "USDB"):
        """Deposit an asset."""
        # we need to check if we have sufficient balance to deposit
        required_wei = int(Decimal(str(quantity)) * Decimal(1e18))
        # we check the approvals
        asset_contract = self.get_contract(asset)

        approved_amount = asset_contract.functions.allowance(
            self.public_key, self.get_contract_address("PROTOCOL")
        ).call()
        if approved_amount < required_wei:
            txn = asset_contract.functions.approve(
                self.get_contract_address("PROTOCOL"), required_wei
            ).build_transaction(
                {
                    "from": self.public_key,
                    "nonce": self.web3.eth.get_transaction_count(self.public_key),
                }
            )
            signed_txn = self.wallet.sign_transaction(txn)
            result = self.web3.eth.send_raw_transaction(signed_txn.rawTransaction)
            # we wait for the transaction to be confirmed
            self.wait_for_transaction(result)

        protocol_contract = self.get_contract("PROTOCOL")
        txn = protocol_contract.functions.deposit(
            self.public_key,
            subaccount_id,
            required_wei,
            asset_contract.address,
        ).build_transaction(
            {
                "from": self.public_key,
                "nonce": self.web3.eth.get_transaction_count(self.public_key),
            }
        )
        signed_txn = self.wallet.sign_transaction(txn)
        result = self.web3.eth.send_raw_transaction(signed_txn.rawTransaction)
        return self.wait_for_transaction(result)

    def wait_for_transaction(self, txn_hash, timeout=TIMEOUT):
        """Wait for a transaction to be confirmed."""
        while True:
            if timeout == 0:
                raise ConnectionError("Timeout")
            try:
                receipt = self.web3.eth.get_transaction_receipt(txn_hash)
                if receipt is not None:
                    break
            except TransactionNotFound:
                time.sleep(1)
            timeout -= 1
        return receipt["status"] == 1

    def get_contract_address(self, name: str):
        """Get the contract address for a specific asset."""
        return self.web3.to_checksum_address(CONTRACTS[self.env][name])

    def get_contract(self, name: str):
        """Get the contract for a specific asset."""
        abis = {
            "USDB": ERC_20_ABI,
            "PROTOCOL": PROTOCOL_ABI,
        }
        return self.web3.eth.contract(
            address=self.get_contract_address(name),
            abi=abis[name],
        )
