# cli/main.py
"""Provides a command-line interface for the package.

The CLI provides the following commands:
- status: Print the last update date.
- update: Update the cache with fresh data from the Finworks API.

The update command has the following options:
- batch: Update the cache in batches of a specified number of days.
- increment: Add a specified number of days to the last update date.
- batches: Update the cache in a specified number of batches.
- roll_back: Roll back the start date by a specified number of days.
- to_date: Update the cache to a specified date.
- test: Use test fixtures instead of API data.

"""
# Immediately suppress numexpr < warning level logs so the autocomplete string
# outputs work form the command line interface.
import logging
import os

from pandas import ExcelWriter

from finworks import get_output_path
logging.getLogger("numexpr").setLevel(logging.WARNING)

import datetime
import click
import pandas as pd
from .finworks import APIClient, Cache, CollectJSONResponses
import pkg_resources

# Get module-named logger.
logger = logging.getLogger(__name__)

# Date string format checker method
def validate_date(ctx, param, value):
    """Check if the date string is in the correct format."""
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Date must be in the format YYYY-MM-DD.")

@click.group()
@click.version_option(pkg_resources.get_distribution("finworks").version, '-v', '--version', message='version==%(version)s')
def cli():
    """Tool for updating the cached Finworks data with fresh API data."""
    pass

@click.command()
@click.option("-s", "--status", is_flag=True, help="Print current API domain and latest cache content date.")
@click.option("-t", "--to-date", type=str, nargs=1, help="Update cache to TEXT date. Overrides the --increment argument.")
@click.option("-i", "--increment", type=int, nargs=1, help="Update cache by INTEGER days.", )
@click.option("-b", "--batch", type=int, nargs=1, help="Batch update cache in blocks of INTEGER days.", )
@click.option("-n", "--batches", type=int, nargs=1, default=None, help="Run INTEGER batches, else run batches till completion.", )
@click.option("-r", "--roll_back", type=int, nargs=1, default=1, help="Roll start date back INTEGER days, overwriting stale data.", )
def update(status, batch, increment, batches, roll_back, to_date):
    """Update the Finworks cache with data from their API.

    With no arguments, the cache is updated with fresh data up till today's date
    by running default size batches. The default behaviour is to roll back the
    start date by 1 day and update the cache to overwrite stale data which could
    have been taken in the middle of the day.

    """
    # Critical check to see if we are in production mode
    if not APIClient.DOMAIN == APIClient.DOMAIN_PROD:
        raise ValueError(
            f"Command only available in production domain {APIClient.DOMAIN_PROD}.")

    cache = Cache()

    if status:
        last_date = cache.last_date()
        logger.info(f"Cache last date is {last_date}")
        logger.info(f"Using the {APIClient.DOMAIN} API.")
        return

    if roll_back:
        if roll_back < 1:
            raise ValueError(
                "Expected ROLL_BACK to be a positive non-zero integer.")

    if batch:
        if batch < 1:
            raise ValueError(
                "Expected BATCH to be a positive non-zero integer.")
        cache.batch_update(batch_size=batch, roll_back=roll_back, batches=batches)
        return

    elif increment:
        if increment < 1:
            raise ValueError(
                "Expected INCREMENT to be a positive non-zero integer.")
        cache.update(increment=increment, roll_back=roll_back)

    elif to_date:
        to_date = validate_date(None, None, to_date)
        cache.update(to_date=to_date, roll_back=roll_back)

    else:
        cache.update(roll_back=roll_back)

@click.command()
@click.option("--date", type=str, nargs=1, help="Collect data on TEXT date. Default's to module's TEST_DATE")
@click.option("--simple", is_flag=True, default=False, help="Keep only the first --number JSON records.")
@click.option("--number", type=int, nargs=1, help="Keep only INTEGER JSON records when using --simple argument.")
@click.option("--basics", is_flag=True, default=True, help="Collect only basics data (models, instruments, investors).")
@click.option("--time-series", is_flag=True, default=True, help="Collect time series data (positions, transactions).")
@click.option("--use-test-data", is_flag=True, default=True, help="Use the test data fixtures instead of the API.")
def collect(date, simple, number, basics, time_series, use_test_data):
    """Collect JSON responses from the Finworks API enpoints and dump to files.
    """
    if date is not None:
        date = pd.to_datetime(date).date()
    CollectJSONResponses(date=date, simple=simple, number=number, basics=basics, time_series=time_series, use_test_data=use_test_data)

@click.command()
@click.option("-i", "--instructions", type=str, nargs=1, help="Path to instructions Excel file.")
@click.option("-d", "--date", type=str, nargs=1, help="Date of holdings used in the reconciliation.")
def post_trade(instructions, date):
    """Post trade holdings reconciliation with instructions.

    Default date is today.
    """
    # Process the date string.
    if date is not None:
        date = validate_date(None, None, date)
    else:
        date = datetime.date.today()
    # Get the instructions from the instructions Excel file and fix its format
    instructions_df = pd.read_excel(instructions)
    instructions_df.set_index("Unnamed: 0", inplace=True)
    instructions_df.index.name = "ticker"
    # Get the holdings as per the reconciliation date.
    cache = Cache()
    data = cache.get_cache_data(from_date=date, to_date=date)
    holdings = data.positions
    model_tickers = holdings.model_ticker.unique().tolist()
    # Break up the instructions path into the path and filename.
    path, filename = os.path.split(instructions)
    for product_ticker in model_tickers:
        # Search for the model ticker in the filename.
        if product_ticker in filename:
            # Get the holdings for the model ticker.
            product_holdings = holdings[holdings.model_ticker == product_ticker]
            break
        else:
            product_holdings = None
    else:
        raise ValueError(
            f"Instructions file {filename} does not contain holdings for any model ticker in the cache data.")
    if product_holdings is None:
        raise ValueError(f"Instructions file {filename} does not contain holdings for model ticker {product_ticker}.")
    # Get product units
    product_units = product_holdings[["ticker", "units"]].groupby("ticker").sum()
    product_units.columns = [product_ticker]
    # Calculate the holdings weights for the model ticker.
    product_value = product_holdings.value.sum()
    product_holdings_pooled = product_holdings[["ticker", "value"]].groupby("ticker").sum()
    product_weights = product_holdings_pooled / product_value
    product_weights.columns = [product_ticker]
    delta = instructions_df.sub(product_weights, fill_value=0.0)
    report = pd.concat(
        [instructions_df[product_ticker], product_weights[product_ticker], delta[product_ticker], product_units[product_ticker]],
        axis=1, keys=["Instructions", "Holdings Weights", "Difference", "Holdings Units"])
    report.fillna(0, inplace=True)
    report.sort_values("Instructions", ascending=False, inplace=True)

    # Write report to Excel file
    file_prefix = filename.split(".")[0]
    xlsx_file_name = f"{file_prefix}-reconciliation-{date}.xlsx"
    xlsx_path = get_output_path(xlsx_file_name)
    table = report
    logger.info(f"Writing reconciliation Excel report to {xlsx_path}")
    with ExcelWriter(xlsx_path, engine="xlsxwriter") as writer:
        table.to_excel(writer, sheet_name="Reconciliation", index=True)
        workbook = writer.book
        worksheet = writer.sheets["Reconciliation"]
        format_percent = workbook.add_format({"num_format": "0.00%", "align": "right"}) # type: ignore
        format_integer = workbook.add_format({"num_format": "#,##0", "align": "right"}) # type: ignore
        worksheet.set_column("B:D", 12, format_percent)
        worksheet.set_column("E:E", 12, format_integer)

cli.add_command(update)
cli.add_command(collect)
cli.add_command(post_trade)

if __name__ == "__main__":
    cli()
