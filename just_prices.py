import logging
import os
import time
from decimal import Decimal
from typing import Dict, List

from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from hundred_x.client import HundredXClient
from hundred_x.enums import Environment

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load configuration
load_dotenv()
INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://localhost:8086")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "keks")
INFLUXDB_USERNAME = os.getenv("INFLUXDB_USERNAME")
INFLUXDB_PASSWORD = os.getenv("INFLUXDB_PASSWORD")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "prices")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
SYMBOL = "ethperp"
COLLECTION_INTERVAL_MILLISECONDS = 0
MAX_LEVELS = 5  # Number of levels to store for each side of the orderbook
SCALING_FACTOR = Decimal('1e18')
d2 = Decimal("2")

def setup_influxdb_client() -> InfluxDBClient:
    client = InfluxDBClient(url=INFLUXDB_URL, org=INFLUXDB_ORG, username=INFLUXDB_USERNAME, password=INFLUXDB_PASSWORD)
    
    buckets_api = client.buckets_api()
    if INFLUXDB_BUCKET not in [bucket.name for bucket in buckets_api.find_buckets().buckets]:
        logger.info(f"Creating bucket: {INFLUXDB_BUCKET}")
        buckets_api.create_bucket(bucket_name=INFLUXDB_BUCKET, org=INFLUXDB_ORG)
    
    return client

def setup_hundredx_client() -> HundredXClient:
    client = HundredXClient(env=Environment.PROD, private_key=PRIVATE_KEY, subaccount_id=0)
    client.login()
    return client

def process_depth(depth: Dict[str, List[List[str]]]) -> Point:
    point = Point("orderbook")
    point.tag("symbol", SYMBOL)

    for side in ['bids', 'asks']:
        for i, (price, amount, _) in enumerate(depth[side][:MAX_LEVELS], start=1):
            price_scaled = float(Decimal(price) / SCALING_FACTOR)
            amount_scaled = float(Decimal(amount) / SCALING_FACTOR)
            point.field(f"{side[:-1]}{i}_price", price_scaled)
            point.field(f"{side[:-1]}{i}_amount", amount_scaled)
    return point

def main():
    influx_client = setup_influxdb_client()
    write_api = influx_client.write_api(write_options=SYNCHRONOUS)
    hundredx_client = setup_hundredx_client()

    logger.info("Starting data collection...")

    try:
        while True:
            try:
                start_time = time.time()
                depth = hundredx_client.get_depth(SYMBOL, granularity=5, limit=MAX_LEVELS)
                point = process_depth(depth)
                write_api.write(INFLUXDB_BUCKET, INFLUXDB_ORG, point)
                logger.info(f"Orderbook data point written for {SYMBOL} in {(time.time() - start_time)*1000:.0f} ms")
            except Exception as e:
                logger.error(f"Error collecting or writing data: {e}")

            if COLLECTION_INTERVAL_MILLISECONDS > 0:
                time.sleep(COLLECTION_INTERVAL_MILLISECONDS/1000)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        influx_client.close()
        logger.info("Data collection stopped.")

if __name__ == "__main__":
    main()
