import os
import time
from decimal import Decimal, getcontext

import pandas as pd
import seaborn as sns
from dotenv import load_dotenv
from matplotlib import pyplot as plt
from tabulate import tabulate

from hundred_x.client import HundredXClient
from hundred_x.enums import Environment

load_dotenv()

def format_value(value, column):
    if isinstance(value, str):
        return value[:7]  # Truncate strings to 7 characters
    elif isinstance(value, Decimal):
        return f'{value:.1%}' if "Share" in column else f'{value:.2f}'
    elif isinstance(value, int):
        return str(value)
    return str(value)

getcontext().prec = 70
de18 = Decimal(1e18)

SYMBOL = "ethperp"
SUBACCOUNT_ID = 0
PRIVATE_KEY = os.environ.get("PRIVATE_KEY")
assert isinstance(PRIVATE_KEY, str), "PRIVATE_KEY not found in .env"
client = HundredXClient(env=Environment.PROD, private_key=PRIVATE_KEY, subaccount_id=SUBACCOUNT_ID)

client.login()
session_status = client.get_session_status()

while True:
    try:
        trade_history = client.get_trade_history(SYMBOL, lookback=500)
        if "trades" not in trade_history:
            print("no trades found, waiting 0.1 seconds before retrying...")
            time.sleep(0.1)
            continue
        trades = trade_history["trades"]

        df = pd.DataFrame(trades)
        df['price'] = df['price'].apply(lambda x: Decimal(x)/de18)
        df['quantity'] = df['quantity'].apply(lambda x: Decimal(x)/de18)

        earliest_trade = df['createdAt'].min()
        earliest_trade_human_readable = pd.to_datetime(earliest_trade, unit='ms').strftime('%Y-%m-%d %H:%M:%S')
        print(f"earliest_trade: {earliest_trade_human_readable}")
        latest_trade = df['createdAt'].max()
        latest_trade_human_readable = pd.to_datetime(latest_trade, unit='ms').strftime('%Y-%m-%d %H:%M:%S')
        print(f"latest_trade:   {latest_trade_human_readable}")
        span = latest_trade - earliest_trade
        print(f"this spans a time period of {span/1000/60:.1f} minutes")
        previous_results = pd.DataFrame()
        if os.path.exists(f"{SYMBOL}.parquet"):
            previous_results = pd.read_parquet(f"{SYMBOL}.parquet")
        merged_results = pd.concat([previous_results, df])
        merged_results = merged_results.drop_duplicates()
        merged_results.to_parquet(f"{SYMBOL}.parquet")
        # formatted_data = [[format_value(row[col], col) for col in merged_results.columns] for _, row in merged_results.iterrows()]
        # print(tabulate(formatted_data, headers=merged_results.columns, tablefmt='pretty'))

        # pivot table of makerAccount and sum(quantity)
        pivot = merged_results.pivot_table(index="makerAccount", values="quantity", aggfunc=["count", "sum"]).reset_index()
        # remove multi-index
        pivot.columns = pivot.columns.droplevel(1)
        pivot.columns = ["makerAccount", "count", "quantity"]
        pivot["avgFillSize"] = pivot["quantity"] / pivot["count"]
        maker = pivot.sort_values(by="quantity", ascending=False)
        maker["quantityShare"] = maker["quantity"] / maker["quantity"].sum()
        formatted_data = [[format_value(row[col], col) for col in maker.columns] for _, row in maker.iterrows()]
        print(tabulate(formatted_data, headers=maker.columns, tablefmt='pretty'))

        taker = merged_results.pivot_table(index="takerAccount", values="quantity", aggfunc=["count", "sum"]).reset_index()
        taker.columns = taker.columns.droplevel(1)
        taker.columns = ["takerAccount", "count", "quantity"]
        taker["avgFillSize"] = taker["quantity"] / taker["count"]
        taker = taker.sort_values(by="quantity", ascending=False)
        taker["quantityShare"] = taker["quantity"] / taker["quantity"].sum()
        formatted_data = [[format_value(row[col], col) for col in taker.columns] for _, row in taker.iterrows()]
        print(tabulate(formatted_data, headers=taker.columns, tablefmt='pretty'))

        combined = pd.merge(maker[["makerAccount", "quantity","quantityShare"]], taker[["takerAccount", "quantity","quantityShare"]], how="outer", left_on="makerAccount", right_on="takerAccount")
        combined["account"] = combined["makerAccount"].fillna(combined["takerAccount"])
        combined = combined.fillna(0)
        combined = combined.drop(columns=["takerAccount", "makerAccount"])
        combined.columns = ["makerVolume", "makerShare", "takerVolume", "takerShare", "account"]
        combined = combined[["account"] + combined.columns[:-1].tolist()]
        combined["totalVolume"] = combined["makerVolume"] + combined["takerVolume"]
        combined["totalShare"] = combined["totalVolume"] / combined["totalVolume"].sum()
        combined = combined.sort_values(by="totalVolume", ascending=False)
        combined["cumShare"] = combined["totalShare"].cumsum()
        formatted_data = [[format_value(row[col], col) for col in combined.columns] for _, row in combined.loc[combined.cumShare<0.999,:].iterrows()]
        print(tabulate(formatted_data, headers=combined.columns, tablefmt='pretty'))

        print(f"added {len(merged_results) - len(previous_results)} rows to {SYMBOL}.parquet")

        # pivot taker x maker with sum(quantity) as value
        pivot = merged_results.pivot_table(index=["takerAccount", "makerAccount"], values="quantity", aggfunc=["sum"]).reset_index()
        pivot.columns = pivot.columns.droplevel(1)
        pivot.columns = ["takerAccount", "makerAccount", "quantity"]
        pivot = pivot.sort_values(by="quantity", ascending=False)

        # create a matrix suitable for a heatmap
        pivot['quantity'] = pd.to_numeric(pivot['quantity'], errors='coerce')
        # shorten each account field to 7 characters
        pivot['takerAccount'] = pivot['takerAccount'].str[:7]
        pivot['makerAccount'] = pivot['makerAccount'].str[:7]
        heatmap_data = pivot.pivot(index='takerAccount', columns='makerAccount', values='quantity')

        # Create the heatmap
        plt.figure(figsize=(12, 10))  # Adjust the figure size as needed
        sns.heatmap(heatmap_data, cmap='YlOrRd', annot=False, cbar=True)

        # Set labels and title
        plt.xlabel('Maker Account')
        plt.ylabel('Taker Account')
        plt.title('2D Heatmap of Quantity by Taker and Maker Account')

        # Show the plot
        # plt.tight_layout()
        # plt.show()
        # Save the plot as a PNG file
        plt.savefig(f"{SYMBOL}_heatmap.png", dpi=300, bbox_inches='tight')
        print(f"saved {SYMBOL}_heatmap.png")

        heatmap_data_normalized = heatmap_data.div(heatmap_data.sum(axis=0), axis=1)
        plt.figure(figsize=(12, 10))
        sns.heatmap(heatmap_data_normalized, cmap='YlOrRd', annot=False, cbar=True, vmin=0, vmax=heatmap_data_normalized.max().max())
        plt.xlabel('Maker Account')
        plt.ylabel('Taker Account')
        plt.title('Relative Proportions of Quantity by Top Taker and Maker Accounts')

        # Rotate x-axis labels for better readability
        plt.xticks(rotation=45, ha='right')

        # Save the plot as a PNG file
        plt.savefig(f"{SYMBOL}_heatmap_normalized.png", dpi=300, bbox_inches='tight')
        print(f"saved {SYMBOL}_heatmap_normalized.png")

        plt.close('all')

        time.sleep(60)
    except Exception as exc:
        print(f"Failed to get trade history: {exc}")
        time.sleep(60)