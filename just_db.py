import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient

# InfluxDB connection details
load_dotenv()
INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://localhost:8086")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "keks")
INFLUXDB_USERNAME = os.getenv("INFLUXDB_USERNAME")
INFLUXDB_PASSWORD = os.getenv("INFLUXDB_PASSWORD")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "prices")

client = InfluxDBClient(url=INFLUXDB_URL, org=INFLUXDB_ORG, username=INFLUXDB_USERNAME, password=INFLUXDB_PASSWORD)
query_api = client.query_api()

def save_plot(timestamps, bids, asks):
    plt.figure(figsize=(12, 6))
    plt.step(timestamps, bids, label='Best Bid')
    plt.step(timestamps, asks, label='Best Ask')
    
    plt.title('Best Bid and Ask Prices Over Time')
    plt.xlabel('Time')
    plt.ylabel('Price')
    plt.legend()
    
    # Format x-axis to show dates nicely
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
    plt.gcf().autofmt_xdate()  # Rotate and align the tick labels
    
    # Save the plot as a PNG file
    plt.savefig('bid_ask_plot.png', dpi=300, bbox_inches='tight')
    print("Plot saved as bid_ask_plot.png")

def parse_data():
    start_time = time.time()
    # Time range for the query (last 24 hours)
    start = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')

    query = f'''
    from(bucket:"{INFLUXDB_BUCKET}")
    |> range(start: {start})
    |> filter(fn: (r) => r._measurement == "orderbook")
    |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
    '''

    result = query_api.query(query)

    total_spread = Decimal(0)
    total_large_spread = Decimal(0)
    count = 0
    large_count = 0

    timestamps = []
    bids = []
    asks = []

    for table in result:
        for record in table.records:
            # fetch values
            timestamp = record.get_time()
            best_bid = Decimal(record.values.get("bid1_price", "0"))
            best_ask = Decimal(record.values.get("ask1_price", "0"))
            bid_amount = Decimal(record.values.get("bid1_amount", "0"))
            ask_amount = Decimal(record.values.get("ask1_amount", "0"))

            # save bids, asks, and timestamps
            timestamps.append(timestamp)
            bids.append(Decimal(record.values.get("bid1_price", "0")))
            asks.append(Decimal(record.values.get("ask1_price", "0")))

            # calculate spread
            spread = best_ask - best_bid
            total_spread += spread
            count += 1

            # calculate spread for orders > 5
            if bid_amount > Decimal("5") and ask_amount > Decimal("5"):
                total_large_spread += spread
                large_count += 1

    avg_spread = total_spread / count if count > 0 else Decimal(0)
    avg_large_spread = total_large_spread / large_count if large_count > 0 else Decimal(0)

    print(f"Average bid-ask spread: {avg_spread:.18f}")
    print(f"Average bid-ask spread for orders > 5: {avg_large_spread:.18f}")
    print(f"  Calculated in: {(time.time() - start_time)*1000:,.0f}ms")

    return timestamps, bids, asks

def check_latest_order():
    """Return the very latest observation. This should only return 1 record."""
    start_time = time.time()
    query = f'''
    from(bucket:"{INFLUXDB_BUCKET}")
    |> range(start: -1h)
    |> filter(fn: (r) => r._measurement == "orderbook")
    |> last()
    '''
    result = query_api.query(query)
    latest_order = next(iter(result[0].records), None)
    print(f"Latest order: {latest_order}")
    print(f"  Calculated in: {(time.time() - start_time)*1000:,.0f}ms")

def check_db_size():
    start_time = time.time()
    query = f'''
    from(bucket:"{INFLUXDB_BUCKET}")
    |> range(start: 0)
    |> filter(fn: (r) => r._measurement == "orderbook")
    |> count()
    '''
    
    result = query_api.query(query)
    
    total_points = sum(record.values["_value"] for table in result for record in table.records)
    
    print(f"Total number of data points: {total_points}")
    
    # Estimate size (very rough estimate, actual size may vary)
    estimated_size_bytes = total_points * 100  # Assume average of 100 bytes per point
    estimated_size_mb = estimated_size_bytes / (1024 * 1024)
    
    print(f"Estimated database size: {estimated_size_mb:.2f} MB")
    print(f"  Calculated in: {(time.time() - start_time)*1000:,.0f}ms")

if __name__ == "__main__":
    timestamps, bids, asks = parse_data()
    check_db_size()
    check_latest_order()
    save_plot(timestamps, bids, asks)

client.close()