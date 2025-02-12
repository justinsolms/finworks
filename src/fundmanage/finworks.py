"""Finworks API data fetch, re-forming (joining) and caching."""
from __future__ import annotations

from copy import copy
import json
import os
import logging
import datetime
import pickle

import ssl
import asyncio
import traceback
from typing import Callable
import aiohttp

import aiohttp.client_exceptions
import pandas as pd
from pandas import DataFrame
from tqdm import tqdm
from asset_base.asset import Listed
from asset_base.manager import Manager
from asset_base.exceptions import FactoryError
from asset_base.accounts import CashAccount, SettlementAccount

from fundmanage.finworks_validator import ModelsValidator, InstrumentsValidator
from fundmanage.finworks_validator import InvestorsValidator
from fundmanage.finworks_validator import PositionsValidator, TransactionsValidator

from fundmanage import get_certificates_path, get_data_path, get_output_path
from .funds import FundsList
from abc import ABC, abstractmethod

from pandas.testing import assert_frame_equal


# Get module-named logger.
logger = logging.getLogger(__name__)


# Dictionary of proxy instrument ISINs to their respective instrument ISINs due
# to the way Finworks treats some corporate actions. The format is the
# (instrument ISIN, proxy ISIN).
PROXY_ISIN_RECORDS = {
    ('ZAE000265625', 'ZAE000316659'),
}

# The first transactions and positions appear 2021-08-02 and 2021-08-07
# respectively
START_DATE = datetime.date(2021, 8, 1)  # NOTE: Question this start date

# Date on which there are transactions too. Note that there should always be
# positions. See rebalance trade instructions emails to Maggie on the 13 Dec'23.
TEST_DATE_BUY = datetime.date(2023, 12, 14)  # Should be rebalance buy trades
TEST_DATE_SELL = datetime.date(2023, 12, 13)  # Should be rebalance sell trades
TEST_DATE = TEST_DATE_BUY

def check_dates(from_date:datetime.date, to_date:datetime.date):
    """Sanity check dates and provide defaults if None."""
    # Default dates
    if from_date is None:
        from_date = START_DATE
    if to_date is None:
        to_date = datetime.date.today()

    # Check dates not in the future
    if from_date > datetime.date.today():
        raise ValueError("The from_date is in the future.")
    if to_date > datetime.date.today():
        raise ValueError("The to_date is in the future.")

    # Check dates not before the START_DATE
    if from_date < START_DATE:
        raise ValueError("The from_date is before the START_DATE.")
    if to_date < START_DATE:
        raise ValueError("The to_date is before the START_DATE.")

    # Check that the from_date is not after the to_date
    if from_date > to_date:
        raise ValueError(
            "The from_date is after the to_date. "
            "Please provide the dates in the correct order."
        )
    return from_date, to_date


class CacheError(BaseException):
    """Any caching related error."""

    pass


class FinworksAPIError(BaseException):
    """Any Finworks API related error."""

    pass


class Task():
    """A task base class to fetch data from the Finworks API.
        Request headers to be sent with the request.

    Parameters
    ----------
    url : str
        The base URL of the Finworks API.
    path : str
        The path of the service within the domain to which the request will be sent.
    table_class : object
        The class object that will be used to store the response data.
    validator_class : finworks_validator.JSONValidator
        The class object that will be used to validate and then format the
        response data.
    headers : dict
        The headers to include in the API request. Example:
        .. code-block:: json
            {
                "Authorization": "Bearer <token>",
                "Content-Type": "application/json"
            }
    ssl_context : ssl.SSLContext
        The SSL context to use for the request.
    kwargs : dict
        Keyword arguments are used for the endpoint parameters.
    """

    PATH = ""

    def __init__(
        self, url: str, path: str, table_class: object, validator_class: object,
        headers: dict, ssl_context: ssl.SSLContext, **kwargs) -> None:
        """Initialization."""
        self.url = url
        self.path = path
        self.url_path = self.url + self.path
        self.table_class = table_class
        self.validator_class = validator_class
        self.headers = headers
        self.ssl_context = ssl_context
        self.params = dict()
        # Keyword arguments are used for the endpoint parameters
        if "date" in kwargs:
            date = kwargs.pop("date")
            self.params.update({"date": date.strftime("%Y-%m-%d")})

        # Set as an exception indicating that the data is not yet fetched. Will
        # be set as exception upon failures or or BaseFrame subclasses of
        # `table_class` argument upon success.
        self.response = Exception("There were not any valid API response yet.")
        # None responses indicating that the data is not yet fetched or was not
        # successfully fetched
        self.exception_records = None
        self.json_records = None

        # Construct the full URL with the path and parameters for logging purposes
        url_obj = aiohttp.helpers.URL(self.url_path)
        self.full_url = str(url_obj.with_query(self.params))

    def __repr__(self) -> str:
        """Return the string representation of the object."""
        return f"{self.__class__.__name__}(url={self.url}, path={self.path}, params={self.params}, table_class={self.table_class}, ssl_context={self.ssl_context})"

    @staticmethod
    def formatter(item):
        """Abstract method to format a single dict item."""
        pass

    @classmethod
    def map_formatter(cls, formatter: Callable, data_list: list[dict]):
        """Maps a formatter to a list of data dict items and any exceptions.

        Parameters
        ----------
        service_name: str
            The name of the calling service. Used to name exception dump files
            on disk.
        formatter : method
            The formatter method which takes as argument one dict item and
            returns a dict item that is formatted.
        data_list : list of dict
            Each item is a dictionary derived from the API json output.

        Returns
        -------
        list[dict]
            The formatted dict items based on the `data_list`.
        list[dict]
            A subset of the  original items from the `data_list` argument that
            had a formatting exception.
        """
        result_list = list()
        exception_list = list()
        for item in data_list:
            try:
                formatted_item = formatter(item)
                # Append formatted item for use
                result_list.append(formatted_item)
            except Exception as ex:
                # Append exception and item for return_debug_info
                exception_list.append((ex, item))

        return result_list, exception_list

    @staticmethod
    def dump_exception_list(service_name, exception_list):
        """Dump the exception list, if it contains items, to a file on disk."""
        if len(exception_list) > 0:
            # Get the date_stamp
            now = datetime.datetime.now()
            date_stamp = now.strftime("%Y-%m-%d-%H-%M-%S")
            # Dump the exceptions to a file
            path = get_data_path("finworks/exceptions")
            # If path does not exist then create it
            if not os.path.isdir(path):
                os.makedirs(path)
            filename = f"{service_name}_{date_stamp}_exceptions.pkl"
            filepath = os.path.join(path, filename)
            with open(filepath, "wb") as f:
                pickle.dump(exception_list, f)
            logger.error(
                "There were API format exceptions. API data was dropped! See %s", filepath)

    # FIXME: Remove or fix this method. It refers to attributes that do not exist
    async def get_test_data(self, path:str, date: datetime.date=None) -> list[dict]:
        """Return test fixture data for the specified API path.

        Note
        ----
        This returns test fixture data, not actual API sourced data.

        Parameters
        ----------
        path : str
            The path of the service within the domain to which the request will
            be sent.
        date : datetime.date
            The date for which the test data is required.

        Returns
        -------
        list[dict]
            List items are each a dict representation of the data content of the
            JSON API response as kept the corresponding test-fixture file.
        """
        # Set the test JSON data path on how the path argument matches the API paths
        # FIXME: This attribute doe not exist
        filename = self.TEST_DATA_FILENAME_DICT[path]
        # Process the data date
        if date is not None:
            filename = filename.format(date_string=date.strftime("%Y-%m-%d"))
        # FIXME: This attribute doe not exist
        filepath = os.path.join(self.TEST_FIXTURES_PATH, filename)
        # Read the test JSON from the TEST_JSON_PATH directory and convert to a
        # dict.
        with open(filepath) as file:
            data = json.load(file)
            logger.debug(f"Read test data from {filepath}.")
        return data

    @property
    def is_completed(self) -> bool:
        """Check if the task is completed.

        This is where the response is checked to see if it is an exception. This
        is where API response exceptions are detected and the task marked as not
        completed.

        An example would be TimeOutError, ContentTypeError, etc.

        """
        return not isinstance(self.response, BaseException)

    async def get(self, session: aiohttp.ClientSession, retry: int) -> BaseFrame:
        """Fetch data from the Finworks API."""
        # Construct the full URL with the path and parameters
        url_path = self.url_path
        full_url = self.full_url
        try:
            logger.debug(f"Getting (try={retry}), url={full_url}")
            async with session.get(url_path, params=self.params,
                                   headers=self.headers, ssl=self.ssl_context
                                   ) as response:
                if response.status != 200:
                    msg = f"Failed response {response.status} from {full_url}"
                    logger.error(msg)
                    # Set the exception as the response
                    self.response = FinworksAPIError(msg)
                else:
                    try:
                        logger.debug(f"Awaiting (try={retry}), url={full_url}")
                        json_records = await response.json()
                    except aiohttp.ContentTypeError as ex:
                        # We got a response but it was not JSON
                        text = await response.text()
                        # Set the exception as the response
                        self.response = FinworksAPIError(
                            f"{ex.message}, url={ex.request_info.url}\n"
                            f"Text received was:\n"
                            f"{text}")
                    except Exception as ex:
                        # Set the exception as the response
                        self.response = ex
                    else:
                        # Got JSON data
                        logger.info(f"Completed (try={retry}), url={full_url}")
                        # TODO: We should examine the JSON records for error messages and respond accordingly and only then release the data
                        json_records = json_records["data"]
                        self.json_records = json_records
        except Exception as ex:
            # Set the exception as the response
            self.response = ex
        else:
            # Validate the models data
            json_validator = self.validator_class()
            results_records, exception_records = json_validator.validate(json_records)
            # If there are exceptions then dump them to a datetime stamped file on disk
            Task.dump_exception_list(self.__class__.__name__, exception_records)
            self.exception_records = exception_records

            # Return the formatted data the appropriate table class.
            # TODO: Instead use the validator class to format the data into the full universe of possible columns despite the JSON 'type' field.
            self.response = self.table_class(pd.DataFrame(results_records))


class ModelsTask(Task):
    """A task to fetch model data from the Finworks API.

    Instantiates the parent ``Task`` class with the ``ModelsValidator`` and
    ``ModelsFrame`` classes for validating and packaging the response data
    respectively.

    Parameters
    ----------
    url : str
        The base URL for the API.
    headers : dict
        The headers to include in the API request.
    ssl_context : ssl.SSLContext
        The SSL context for secure connections.
    **kwargs : dict
        Additional keyword arguments to pass to the parent class.

    """

    PATH = "/api/modelmanager/model-portfolios"
    TEST_DATA_FILENAME = "models.json"

    def __init__(
        self, url: str, headers:dict, ssl_context: ssl.SSLContext, **kwargs) -> None:
        """Initialization."""
        super().__init__(
            url, self.PATH, ModelsFrame, ModelsValidator,
            headers, ssl_context, **kwargs)

    @staticmethod
    def formatter(item):
        # Avoid modifying the original as we may need to refer to it later
        item = copy(item)
        # Rename model fields
        item["model_ticker"] = item.pop("Code")
        item["model_portfolio_id"] = item.pop("Model portfolio id")
        item["name"] = item.pop("Name")
        # Flatten nested splits flat with the other dict items
        for split in item["Splits"]:
            instrument_id = split["Instrument id"]
            value = split["Split"]
            assert (
                value["type"] == "Percentage"
            ), "The split value `type` must be `Percentage`."
            item[instrument_id] = value["value"]
        # Pop off flattened splits
        item.pop("Splits")
        return item

class InstrumentsTask(Task):
    """A task to fetch instrument data from the Finworks API.

    Instantiates the parent ``Task`` class with the ``InstrumentsValidator`` and
    ``InstrumentsFrame`` classes for validating and packaging the response data
    respectively.

    Parameters
    ----------
    url : str
        The base URL for the API.
    headers : dict
        The headers to include in the API request.
    ssl_context : ssl.SSLContext
        The SSL context for secure connections.
    **kwargs : dict
        Additional keyword arguments to pass to the parent class.

    """



    PATH = "/api/modelmanager/instruments"
    TEST_DATA_FILENAME = "instruments.json"

    def __init__(self, url: str, headers:dict, ssl_context: ssl.SSLContext, **kwargs) -> None:
        """Initialization."""
        super().__init__(
            url, self.PATH, InstrumentsFrame, InstrumentsValidator,
            headers, ssl_context, **kwargs)

    @staticmethod
    def formatter(item):
        # Avoid modifying the original as we may need to refer to it later
        item = copy(item)
        # Rename fields
        item.pop("Instrument provider")
        item.pop("Name")
        item["isin"] = item.pop("ISIN Number")
        item["instrument_id"] = item.pop("Instrument id")
        item["ticker"] = item.pop("Code")
        item["instrument_type"] = item.pop("Instrument type")
        item["status"] = item.pop("Status")
        item["currency"] = item.pop("Currency")
        return item

class InvestorsTask(Task):
    """A task to fetch investor data from the Finworks API.

    Instantiates the parent ``Task`` class with the ``InvestorsValidator`` and
    ``InvestorsFrame`` classes for validating and packaging the response data
    respectively.

    Parameters
    ----------
    url : str
        The base URL for the API.
    headers : dict
        The headers to include in the API request.
    ssl_context : ssl.SSLContext
        The SSL context for secure connections.
    **kwargs : dict

    """

    PATH = "/api/modelmanager/investors"
    TEST_DATA_FILENAME = "investors.json"

    def __init__(self, url: str, headers: dict, ssl_context: ssl.SSLContext, **kwargs) -> None:
        """Initialization."""
        super().__init__(
            url, self.PATH, InvestorsFrame, InvestorsValidator,
            headers, ssl_context, **kwargs)

    @staticmethod
    def formatter(item):
        # Avoid modifying the original as we may need to refer to it later
        item = copy(item)
        # Pop off unwanted fields.
        item.pop("Policy number")
        item.pop("Description")
        item.pop("Product")
        if "Investor account id" in item:
            # NOTE: Was contract_number. This was to be removed some day
            item.pop("Investor account id")
        if "Account number" in item:
            # NOTE: Was contract_number. This was to be removed some day
            item.pop("Account number")
        # Rename fields
        item["client_account_id"] = item.pop("Client account id") # NOTE: This is not in the Finworks specification
        item["contract_id"] = item.pop("Contract id")  # NOTE: Was old UUID
        item["contract_number"] = item.pop("Contract number") # TODO: Rename to contract_number or portfolio_number
        item["id_number"] = item.pop("Identification number")
        item["model_portfolio_id"] = item.pop("Modelportfolio")
        item["take_on_date"] = item.pop("Take On Date")
        # Status
        popped = item.pop("Status")
        item["status"] = popped["identifier"]
        # TODO: Make boolean
        item["active"] = popped["active"]
        # Capitalize names
        name_str = item.pop("Investor name")
        investor_names = [n.capitalize() for n in name_str.split(" ")]
        item["name"] = " ".join(investor_names)
        return item


class PositionsTask(Task):
    """A task to fetch position data from the Finworks API.

    Instantiates the parent ``Task`` class with the ``PositionsValidator`` and
    ``PositionsFrame`` classes for validating and packaging the response data
    respectively.

    Parameters
    ----------
    url : str
        The base URL for the API.
    headers : dict
        The headers to include in the API request.
    ssl_context : ssl.SSLContext
        The SSL context for secure connections.
    **kwargs : dict

    """

    PATH = "/api/modelmanager/holdings"
    TEST_DATA_FILENAME = "positions_{date_string}.json"

    def __init__(self, url: str, headers, ssl_context: ssl.SSLContext, **kwargs) -> None:
        """Initialization."""
        # Check the date keyword argument argument is present
        if "date" not in kwargs:
            raise ValueError("The date keyword argument is required.")
        super().__init__(
            url, self.PATH, PositionsFrame, PositionsValidator,
            headers, ssl_context, **kwargs)

    @staticmethod
    def formatter(item):
        # Avoid modifying the original as we may need to refer to it later
        item = copy(item)
        # Pop off unwanted fields.
        if "Investor account id" in item:
            # NOTE: Was contract_number. This was to be removed some day
            item.pop("Investor account id")
        item.pop("Market Value in System Currency")
        item.pop("Instrument account number")
        # Renames
        item["date"] = item.pop("Date")
        item["contract_id"] = item.pop("Contract id") # TODO: Rename to contract_id
        item["client_account_id"] = item.pop("Client account id")
        item["instrument_id"] = item.pop("Instrument id")
        # The market price. Assert it's fund currency as the  currency
        # going forward. Assert the value going forward.
        popped = item.pop("Market Value in Fund Currency")
        assert (
            popped["type"] == "Money"
        ), "Positions market value in fund currency `type` must be `Money`."
        currency = popped["currency"]
        value = float(popped["value"])
        # The `Price` field.
        popped = item.pop("Latest available price")
        assert popped["type"] == "Price", "Positions price type discrepancy."
        assert (
            popped["currency"] == currency
        ), "Positions price currency discrepancy."
        assert (
            popped["Instrument id"] == item["instrument_id"]
        ), "Positions instrument price instrument id discrepancy."
        price = float(popped["value"])
        # Get type and number of units
        popped = item.pop("Units")
        type_ = popped["type"]
        if type_ == "Unit":
            assert (
                popped["Instrument id"] == item["instrument_id"]
            ), "Positions units units instrument id discrepancy."
            units = float(popped["value"])
        elif type_ == "Money":
            assert (
                popped["currency"] == currency
            ), "Positions units money currency discrepancy."
            units = float(popped["value"])
            price = 1.0
        else:
            raise Exception("Unexpected units type.")
        assert round(value, 2) == round(
            units * price, 2
        ), "Positions price-units and value discrepancy"
        item["type"] = type_
        item["currency"] = currency
        item["price_date"] = item.pop("Price date")
        item["price"] = price
        item["units"] = units
        item["value"] = value
        return item

class TransactionsTask(Task):
    """A task to fetch transaction data from the Finworks API.

    Instantiates the parent ``Task`` class with the ``TransactionsValidator`` and
    ``TransactionsFrame`` classes for validating and packaging the response data
    respectively.

    Parameters
    ----------
    url : str
        The base URL for the API.
    headers : dict
        The headers to include in the API request.
    ssl_context : ssl.SSLContext
        The SSL context for secure connections.
    **kwargs : dict
    """

    PATH = "/api/modelmanager/transactions"
    TEST_DATA_FILENAME = "transactions_{date_string}.json"

    def __init__(self, url: str, headers:dict, ssl_context: ssl.SSLContext, **kwargs) -> None:
        """Initialization."""
        # Check the date keyword argument argument is present
        if "date" not in kwargs:
            raise ValueError("The date keyword argument is required.")
        super().__init__(
            url, self.PATH, TransactionsFrame, TransactionsValidator,
            headers, ssl_context, **kwargs)

    @staticmethod
    def formatter(item):
        # Avoid modifying the original as we may need to refer to it later
        item = copy(item)
        # Pop off unwanted fields.
        if "Investor account id" in item:
            # NOTE: Was contract_number. This was to be removed some day
            item.pop("Investor account id")
        item.pop("Instrument account number")
        # Renames
        item["date"] = item.pop("Date")
        # Unique by transaction id
        item["transaction_id"] = item.pop("Transaction id")
        item["contract_id"] = item.pop("Contract id")
        item["client_account_id"] = item.pop("Client account id")
        item["instrument_id"] = item.pop("Instrument id")
        item["is_cashflow"] = item.pop("Is Cashflow")
        # Classification
        item["type"] = item.pop("Type")
        item["sub_type"] = item.pop("Sub type")
        transact_id = item["transaction_id"]
        instrument_id = item["instrument_id"]
        # Assert the instrument id going forward.
        # The `Amount` item. Assert it's currency as the transaction currency
        # going forward.
        popped = item.pop("Amount")
        currency = popped["currency"]  # Transaction currency
        assert (
            popped["type"] == "Money"
        ), f"Transaction value type discrepancy, TID={transact_id}."
        value = float(popped["value"])  # Transaction value
        # The `Units` item.
        popped = item.pop("Units")
        type_ = popped["type"]
        if popped["type"] == "Money":
            units = float(popped["value"])
        elif popped["type"] == "Unit":
            units = float(popped["value"])
            assert (
                popped["Instrument id"] == instrument_id
            ), f"Transaction units instrument id discrepancy, TID={transact_id}."
        else:
            raise Exception("Unexpected units type.")
        # The `Price` field. If the units type is `Money` then ignore checks
        # as there are instrument_id discrepancies as pointed out by Otto -
        # Finworks (email: Transaction price instrument id discrepancy, 27
        # Aug 2021, 17:18)
        popped = item.pop("Price")
        if type_ != "Money" and popped is not None:
            # assert popped['Instrument id'] == instrument_id, \
            #     f'Transaction price instrument id discrepancy, TID={transact_id}.'
            assert (
                popped["currency"] == currency
            ), f"Transaction price currency discrepancy, TID={transact_id}."
            assert (
                popped["type"] == "Price"
            ), f"Transaction price type discrepancy, TID={transact_id}."
            price = float(popped["value"])  # Transaction price
        else:
            price = 1.0
        # Add fields to item
        item["currency"] = currency
        item["price"] = price
        item["units"] = units
        item["value"] = value
        item["processed_date"] = item.pop("Processed date")
        item["description"] = item.pop("Description")

        return item

class APIClient(object):
    """A class to asynchronously fetch data from the Finworks API.

    Parameters
    ----------
    test_url : str, optional
        The URL of the test server. If provided then the API client will use
        this URL instead of the default URL.
    """

    # Comment out the unused operational mode.
    ENVIRONMENT = "production"
    ENVIRONMENT = "test"

    # Domains to choose from
    DOMAIN_PROD = "secure.aospartner.com"
    DOMAIN_TEST = "test.aospartner.com"

    # Security keys and token
    KEY = "cert.key"
    CRT = "cert.crt"
    VERIFY = "cert.pem"
    TOKEN = "QyT7oTnIvmiq5swQ"


    if ENVIRONMENT == "test":
        DOMAIN = DOMAIN_TEST
    elif ENVIRONMENT == "production":
        DOMAIN = DOMAIN_PROD
    else:
        raise Exception("Invalid DOMAIN selection.")

    # Connector settings
    CONNECTION_LIMIT = 8 # Maximum number of connections
    CONNECTION_LIMIT_PER_HOST = 4  # Maximum number of connections per host
    TTL_DNS_CACHE = 10 * 60  # DNS cache time-to-live seconds
    ENABLE_CLEANUP_CLOSED = True  # Clean up closed SSL transports

    # Client timeout in seconds
    TOTAL_TIMEOUT = 20 * 60  # seconds
    CONNECT_TIMEOUT = 10 * 60  # seconds
    READ_TIMEOUT = 6 * 60  # seconds

    # Number of retries - on the last one we will abort instead of trying again
    RETRY_LIST = [0, 1, 2, 3]

    def __init__(self, test_url: str=None) -> None:
        """Initialization."""
        if test_url is not None:
            self.url = test_url
        else:
            self.url = f"https://{self.DOMAIN}"

        self.tasks_list = []

        # Set up SSL context with server domain certificate verification
        key = get_certificates_path(os.path.join(self.DOMAIN, self.KEY))
        crt = get_certificates_path(os.path.join(self.DOMAIN, self.CRT))
        self.headers = { "Authorization: Bearer": self.TOKEN, "Content-Type": "application/json" }
        self.ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        self.ssl_context.load_cert_chain(certfile=crt, keyfile=key)

        logger.info(f"API client initialized with url={self.url}")

    def __repr__(self) -> str:
        """Return the string representation of the object."""
        return f"APIClient(url={self.url}, ssl_context={self.ssl_context})"

    def __str__(self) -> str:
        """Return the string representation of the object."""
        # List the contents of the task list
        for task in self.tasks_list:
            print(task)

    def add_task(self, task: object, **kwargs) -> None:
        """Add a task to the task list."""
        if not issubclass(task, Task):
            ValueError("The task argument must be a subclass of the Task class.")
        # Instantiate the `Task` object and append it to the task list
        task_obj = task(self.url, self.headers, self.ssl_context, **kwargs)
        self.tasks_list.append(task_obj)

    async def tasker(self, retry, incomplete_tasks_list):
        """Gathering of tasks under the aiohttp.ClientSession context."""
        # Prepare aiohttp.ClientSession settings objects
        connector = aiohttp.TCPConnector(
            limit=self.CONNECTION_LIMIT,
            limit_per_host=self.CONNECTION_LIMIT_PER_HOST,
            ttl_dns_cache=self.TTL_DNS_CACHE,
            enable_cleanup_closed=self.ENABLE_CLEANUP_CLOSED,
        )
        timeout = aiohttp.ClientTimeout(
            total=self.TOTAL_TIMEOUT,
            connect=self.CONNECT_TIMEOUT,
            sock_connect=self.CONNECT_TIMEOUT,
            sock_read=self.READ_TIMEOUT,
            ceil_threshold=self.TOTAL_TIMEOUT,
        )
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # TODO: Improve output with attributes
            logger.debug(f"Client session with connector={connector}, timeout={timeout}, session={session}.")
            # Make a list of tasks to gather
            tasks_todo_list = [task.get(session, retry) for task in incomplete_tasks_list]
            # Fetch data
            responses_list = await asyncio.gather(*tasks_todo_list, return_exceptions=True)
        return responses_list

    def fetch(self, return_tasks: bool=False):
        """Fetch data from the Finworks API.

        Parameters
        ----------
        return_tasks : bool, optional
            If True then return a list of ``Task`` objects. Else return a list
            of ``Task.response`` attributes for each ``Task`` object. Defaults
            to False.

        Returns
        -------
        list
            See the ``return_tasks`` parameter for the return type.
        """
        # Test if there are tasks in the task list
        if not self.tasks_list:
            raise ValueError("Unexpected empty task list.")

        # Loop that retries items in the tasks list that failed to fetch
        for retry in self.RETRY_LIST:
            incomplete_tasks_list = [task for task in self.tasks_list if not task.is_completed]
            # Check retry status against incomplete tasks
            if incomplete_tasks_list:
                if retry != self.RETRY_LIST[0]:  # Skip warnings for the first try
                    for task in incomplete_tasks_list:
                        task_name = task.__class__.__name__
                        logger.warning(f"Failed {task_name}, {task.response}, url={task.full_url}")
                elif retry == self.RETRY_LIST[-1]:  # Last retry - we give up here
                    logger.critical("There are incomplete tasks after too many retires. Here follow full exceptions logs:")
                    for task in incomplete_tasks_list:
                        # The response contains the exception
                        task_name = task.__class__.__name__
                        ex = task.response
                        logger.error(f"Failed {task_name} caused by the exception below:\n%s", "".join(traceback.format_exception(None, ex, ex.__traceback__)))
                    # Give up on the last retry
                    raise FinworksAPIError("There are incomplete tasks after too many retires - aborting.")
                else:
                    # Log an explicit retry warning
                    logger.warning(f"Retrying {len(incomplete_tasks_list)} tasks.")
            else:
                break  # No incomplete tasks

            asyncio.run(self.tasker(retry, incomplete_tasks_list))

        # The tasks list is now complete as far as is possible. The task list
        # must now be reset to empty before being usd again or else completed
        # tasks will be re-executed.
        tasks_list = self.tasks_list
        self.tasks_list = []

        if return_tasks:
            # Return the tasks populated with responses if all went well, else
            # populated with exceptions where it did not go well
            return tasks_list
        else:
            # By default return the responses
            return [task.response for task in tasks_list]


class BaseFrame(ABC):
    """Abstract base class for all the other frame classes.

    Parameters
    ----------
    data : pd.DataFrame
        The data table already proceeded into a DataFrame from whatever it was.
    merged : bool, optional
        If True then the data is merged with instrument data. Defaults to False.
        This alters the expected columns in the data.
    """
    COLUMNS = []
    COLUMNS_EXTRA = []
    KEY_COLUMNS = []

    def __init__(self, data: pd.DataFrame, merged: bool=False) -> None:
        # Check data is a DataFrame
        self.merged = merged

        if not isinstance(data, pd.DataFrame):
            raise ValueError("The data argument is not a DataFrame.")

        # If the dataframe is empty then make it a DataFrame with the expected
        # columns in the correct column order.
        if data.empty:
            if not self.merged:
                self.data = pd.DataFrame(columns=self.COLUMNS)
            else:
                self.data = pd.DataFrame(columns=self.COLUMNS + self.COLUMNS_EXTRA)
        else:
            self.data = data

        # Call the subclass methods
        self.data_mods()
        self.check()

        # Sort by child class key columns
        self.data = self.data.sort_values(by=self.KEY_COLUMNS)
        # Reset index
        self.data = self.data.reset_index(drop=True)

    def __repr__(self):
        """Return the string representation of the object."""
        return f"{self.__class__.__name__}(data=\n{self.data!r}, merged={self.merged})"

    @abstractmethod
    def data_mods(self):
        """Modifications to the data before it is passed to the DataFrame.

        Note
        ----
        Overload this method in the child class. The child class should call
        this method using `super().data_mods()`.
        """
        self.data = self.data.mask(self.data == "")  # Convert empty strings to NaNs

    @abstractmethod
    def check(self):
        """Abstract method to check the integrity of the data."""
        pass

    @property
    def empty(self):
        """Check if the data is empty."""
        return self.data.empty


class ModelsFrame(BaseFrame):
    """Encapsulation of model instrument weights data with built in checking.

    Parameters
    ----------
    json_list : list
        A list of dictionaries containing model data.
    merged : bool, optional
        If True then the data is merged with instrument data. Defaults to False.
        This alters the expected columns in the data.
    normalized : bool, optional
        If True then the data is already normalized and does not need to be
        un-pivoted. Defaults to False.

    The encapsulated table's rows are unique by the `model_portfolio_id` and
    `instrument_id`. There is a one-to-one relationship between the
    `model_portfolio_id` and the `model_ticker`. Columns:

    ==================  ===============================
    Column Name         Description
    ==================  ===============================
    model_ticker        Our unique model ticker
    name                Product or model name
    model_portfolio_id  Unique Finworks model id
    instrument_id       Unique security id
    value               Weight in the model
    ==================  ===============================

    If the `merged` flag is True then the following columns are also present:

    ==================  ===============================
    Column Name         Description
    ==================  ===============================
    isin                Security ISIN Number
    ticker              Exchange ticker
    status              Open or Closed status
    ==================  ===============================

    """

    COLUMNS = [
        "model_ticker", "name", "model_portfolio_id", "instrument_id", "value"]
    COLUMNS_EXTRA = ["isin", "ticker", "status"]
    KEY_COLUMNS = ["model_portfolio_id", "instrument_id"]

    def __init__(self, data: pd.DataFrame, merged: bool=False, normalized: bool=False) -> None:
        """Initialization."""
        self.normalized = normalized
        # Check data is not empty
        if data.empty:
            raise ValueError("Unexpected empty data argument.")
        if normalized or self.normalized:
            pass
        else:
            data = self.un_pivot(data)
        super().__init__(data, merged)

    def data_mods(self):
        return super().data_mods()

    def check(self):
        """Run tests on data."""
        if not isinstance(self.data, pd.DataFrame):
            raise ValueError("Response is not a DataFrame")
        if self.data.empty:
            raise ValueError("Response is empty.")
        if not self.merged:
            if self.data.columns.tolist() != self.COLUMNS:
                raise ValueError("Unexpected columns in data.")
        else:
            if self.data.columns.tolist() != self.COLUMNS + self.COLUMNS_EXTRA:
                raise ValueError("Unexpected columns in data.")
        if self.data.duplicated(subset=self.KEY_COLUMNS).any():
            raise ValueError("Non-unique by KEY_COLUMNS attribute.")
        if not (self.data.groupby('model_portfolio_id')['model_ticker'].nunique().max() == 1 and self.data.groupby('model_ticker')['model_portfolio_id'].nunique().max() == 1):
            raise ValueError("There isn't a one-to-one relationship between model_portfolio_id and model_ticker.")

    def un_pivot(self, data):
        """Un-Pivot models table to first normal form.

        Un-Pivot models table to first normal form, i.e., from columns of
        instruments to unique rows.
        """
        # Un-pivot (melt)
        data = data.melt(
            id_vars=["model_ticker", "name", "model_portfolio_id"],
            var_name="instrument_id",
        )
        # The original model table had model_ticker rows and instrument columns.
        # As a consequence there usually are a lot of NaNs where model_tickers
        # did not have weight entries for every instrument. These show up as
        # NaNs for weights (value column) in the normal form table and these
        # must be removed.
        data = data.dropna(axis="index", how="any", subset=["value"])
        self.normalized = True
        return data

    def merge(self, instruments: InstrumentsFrame):
        """Merge two models dataframes."""
        assert isinstance(instruments, InstrumentsFrame)
        # Merge instruments 'isin', 'ticker', 'status' into models table
        models_df = pd.DataFrame.merge(
            self.data,
            instruments.data[
                ["instrument_id", "isin", "ticker", "status"]
            ].drop_duplicates(),
            on="instrument_id",
            how="left",
            )
        # Check that all instruments in the  models table are in the instruments
        # table.
        if models_df["isin"].isnull().any():
            raise ValueError(
                "Not all instruments in models table are in instruments table.")
        self.data = models_df
        self.merged = True


class InstrumentsFrame(BaseFrame):
    """Encapsulation of instrument data with built in checking.

    Parameters
    ----------
    json_list : list
        A list of dictionaries containing instrument data.

    The encapsulated table's rows are unique by the `isin`. There is a one to
    one relationship between the `isin` and the `instrument_id`. Columns:

    ==================  ===============================
    Column Name         Description
    ==================  ===============================
    isin                Security ISIN Number
    instrument_id       Unique security id
    ticker              Exchange ticker
    instrument_type     An ETF, Share, Unit Trust etc.
    status              Open or Closed status
    currency            ISO 3-Letter currency code
    ==================  ===============================
    """

    COLUMNS = [
        "isin", "instrument_id", "ticker",
        "instrument_type", "status", "currency", ]
    KEY_COLUMNS = ["isin"]

    def __init__(self, data: pd.DataFrame) -> None:
        """Initialization."""
        # Check data is not empty
        if data.empty:
            raise ValueError("Unexpected empty data argument.")
        # We use the instrument ticker in place of missing ISIN numbers. This
        # happens in the case of the cash and settlement accounts. We need a
        # unique ISIN for each instrument and so NaN ISINs won't do and we use
        # the cash ticker instead
        super().__init__(data, False)

    def data_mods(self):
        """Modifications to the data before it is passed to the DataFrame."""
        # We use the instrument ticker in place of missing ISIN numbers. This
        # happens in the case of the cash and settlement accounts. We need a
        # unique ISIN for each instrument and so NaN ISINs won't do and we use
        # the cash ticker instead
        super().data_mods()
        isin = self.data["isin"]
        ticker = self.data.ticker
        self.data["isin"] = isin.mask(isin.isna(), ticker)
        # Add the missing proxy_isin column to the instruments data if it does
        # not exist
        if 'proxy_isin' not in self.data.columns:
            proxy_df = pd.DataFrame(PROXY_ISIN_RECORDS, columns=('isin', 'proxy_isin'))
            self.data = pd.merge(self.data, proxy_df, on='isin', how='left')

    def check(self):
        """Run tests on data."""
        if not isinstance(self.data, pd.DataFrame):
            raise ValueError("Response is not a DataFrame")
        if self.data.empty:
            raise ValueError("Response is empty.")
        if 'proxy_isin' in self.data.columns:
            if self.data.columns.tolist() != self.COLUMNS + ['proxy_isin']:
                raise ValueError("Unexpected columns in data.")
        else:
            if self.data.columns.tolist() != self.COLUMNS:
                raise ValueError("Unexpected columns in data.")
        if self.data.duplicated(subset=self.KEY_COLUMNS).any():
            raise ValueError("Non-unique by KEY_COLUMNS attribute.")
        if not (self.data.groupby('isin')['instrument_id'].nunique().max() == 1 and self.data.groupby('instrument_id')['isin'].nunique().max() == 1):
            raise ValueError("There isn't a one-to-one relationship between isin and instrument_id.")


class InvestorsFrame(BaseFrame):
    """Encapsulation of investor contracts and accounts with built in checking.

    Parameters
    ----------
    json_list : list
        A list of dictionaries containing investor data.
    merged : bool, optional
        If True then the data is merged with model portfolio data. Defaults to
        False.

    The encapsulated table's rows are unique by the `client_account_id`. There
    is a one to many relationship between the `contract_id` and the
    `client_account_id` which establishes the relationship between a specific
    client contract and its many client portfolio accounts. Columns:

    ==================  =================================
    Column Name         Description
    ==================  =================================
    client_account_id   Client portfolio account unique id
    contract_id         Client contract unique id
    contract_number     Client contract unique number
    id_number           Investor identity number
    model_portfolio_id  Model portfolio id
    take_on_date        Investor take on date
    status              existingBusiness | newBusiness
    active              True | False
    name                Full names of the investor
    ==================  =================================

    If the `merged` flag is True then the following columns are also present:

    ==================  =================================
    Column Name         Description
    ==================  =================================
    model_ticker        Our unique model ticker
    ==================  =================================

    """
    COLUMNS = [
        "client_account_id", "contract_id", "contract_number",
        "id_number", "model_portfolio_id", "take_on_date",
        "status", "active", "name"]
    COLUMNS_EXTRA = ["model_ticker"]
    KEY_COLUMNS = ["client_account_id"]

    def __init__(self, data: pd.DataFrame, merged:bool=False) -> None:
        """Initialization."""
        # Check data is not empty
        if data.empty:
            raise ValueError("Unexpected empty data argument.")
        super().__init__(data, merged)

    def data_mods(self):
        return super().data_mods()

    def check(self):
        """Run tests on data and report True of Ok."""
        if not isinstance(self.data, pd.DataFrame):
            raise ValueError("Response is not a DataFrame")
        if self.data.empty:
            raise ValueError("Response is empty.")
        if not self.merged:
            if self.data.columns.to_list() != self.COLUMNS:
                raise ValueError("Unexpected columns in response DataFrame.")
        else:
            if self.data.columns.to_list() != self.COLUMNS + self.COLUMNS_EXTRA:
                raise ValueError("Unexpected columns in response DataFrame.")
        if self.data["client_account_id"].isnull().values.any():
            raise ValueError("Missing values in client_account_id.")
        if self.data.duplicated(subset=self.KEY_COLUMNS).any():
            raise ValueError("Non-unique by KEY_COLUMNS attribute.")
        unique_pairs = self.data[["client_account_id", "contract_id"]].drop_duplicates()
        if not unique_pairs["client_account_id"].is_unique:
            raise ValueError("Values in contract_id have a common value in client_account_id.")

    def merge(self, models: ModelsFrame):
        """Merge two investors dataframes."""
        assert isinstance(models, ModelsFrame)
        # Merge models 'model_ticker' into investors table
        investors_df = pd.DataFrame.merge(
            self.data,
            models.data[
                ["model_portfolio_id", "model_ticker"]
            ].drop_duplicates(),
            on="model_portfolio_id",
            how="left",
            )
        # Check that all models in the  investors table are in the models table.
        if investors_df["model_ticker"].isnull().any():
            raise ValueError(
                "Not all models in investors table are in models table.")
        # Return the merged table with the correct type
        self.data = investors_df
        self.merged = True


class TimeSeriesFrame(BaseFrame):
    """Encapsulation of time series data with built in checking.

    Parameters
    ----------
    json_list : list
        A list of dictionaries containing position data.
    merged : bool, optional
        If True then the data is merged with model portfolio data. Defaults to
        False.

    """

    def __init__(self, data: pd.DataFrame, merged:bool=False) -> None:
        """Initialization."""
        super().__init__(data, merged)

    def data_mods(self):
        """Modifications to the data before it is passed to the DataFrame."""
        # Remove entries with zero units if there is data at all. This may also
        # help as there are duplicated entries existing with 0 units(see check
        # method).
        super().data_mods()
        if not self.data.empty:
            # Delete bloating rows with zero units
            self.data = self.data[self.data.units != 0]
            # Convert dates to datetime
            self.data["date"] = pd.to_datetime(self.data["date"])

    def slice(self, boolean_series):
        """Slice the data rows based on a boolean series."""
        # Test for boolean series
        if not isinstance(boolean_series, pd.Series) and boolean_series.dtype != bool:
            raise ValueError("Boolean series must be a pandas.Series of dtype bool.")
        # Test boolean series length against number of data rows
        if len(boolean_series) != len(self.data):
            raise ValueError("Boolean series length must be equal to the number of data rows.")
        if not self.empty:
            self.data = self.data[boolean_series]

    def update(self, new: TimeSeriesFrame):
        """Update the data with new data.

        Uses the ``KEY_COLUMNS`` class attribute to update the data.


        Parameters
        ----------
        new : TimeSeriesFrame
            New data to update with.
        """
        if self.merged != new.merged:
            raise ValueError(
                "Current data and new data must have the same merged flag.")

        def updater(df1, df2, keys):
            """df1: existing data, df2: incoming data"""

            # We shall update by date index. The pandas.DataFrame.update updates
            # by index. In this Data class the date column in not an index so
            # set it as such. We shall reset the index in the updated result.
            df1 = df1.set_index(keys)
            df2 = df2.set_index(keys)
            # Combine. Keep values in incoming df2 and overwrite df1. Read
            # combine_first docs carefully!
            df = df2.combine_first(df1)
            # In this Data class the date column in not an index so reset it.
            df = df.reset_index(drop=False)  # Note this alters the index content

            return df

        if self.empty:
            self.data = new.data
        else:
            self.data = updater(self.data, new.data, self.KEY_COLUMNS)

        # Re-rank columns which may be altered by `updater`. Should be okay as
        # they have previously been checked by the `check` method.
        if not self.merged:
            self.data = self.data[self.COLUMNS]
        else:
            self.data = self.data[self.COLUMNS + self.COLUMNS_EXTRA]

    @classmethod
    def concat(cls, obj_list):
        """Needed to produce a PositionsFrame class result from a list of dataframes.

        Parameters
        ----------
        obj_list : list
            A list of TimeSeriesFrame (or child class) objects.

        Returns
        -------
        cls
            A TimeSeriesFrame (or child class) object.
        """
        # Check that all objects in the list are TimeSeriesFrame objects or subclass classes thereof.
        if not all(isinstance(obj, cls) for obj in obj_list):
            raise ValueError("All objects must be TimeSeriesFrame (or subclass) objects.")
        # Check that the merged flags of all object in the list are the same.
        if not all(obj.merged == obj_list[0].merged for obj in obj_list):
            raise ValueError("All objects must have the same merged flag.")
        # Extract the data from the objects in the list that have columns
        data_list = [obj.data for obj in obj_list if not obj.data.columns.empty]
        # Concatenate the dataframes list if it is not empty
        if len(data_list) > 1:
            data = pd.concat(data_list, axis='index', ignore_index=True)
        elif len(data_list) == 1:
            data = data_list[0]
        else:
            raise ValueError(
                "Cannot concatenate TimeSeriesFrame objects. "
                "All objects have empty data columns.")
        # Return the concatenated data as a TimeSeriesFrame object
        return cls(data, obj_list[0].merged)


class PositionsFrame(TimeSeriesFrame):
    """Encapsulation of investor account positions data with built in checking.

    Parameters
    ----------
    json_list : list
        A list of dictionaries containing position data.
    merged : bool, optional
        If True then the data is merged with model portfolio data. Defaults to
        False.

    The encapsulated table's rows are unique by the `date`, `client_account_id`
    and `instrument_id`. Columns:

    ==================  ===============================
    Column Name         Description
    ==================  ===============================
    date                Positions date yyyy-mm-dd
    contract_id         Finworks contract id
    client_account_id   Client portfolio account unique id
    instrument_id       Finworks instrument id
    type                Category `Unit` or `Money`
    currency            ISO 3-letter currency code
    price_date          Date of the price column
    price               price in currency units
    units               Number of units held
    value               Priced value of units held
    ==================  ===============================

    If the `merged` flag is True then the following columns are also present:

    ==================  ===============================
    Column Name         Description
    ==================  ===============================
    model_portfolio_id  Model portfolio id
    model_ticker        Our unique model ticker
    isin                Security ISIN Number
    ticker              Exchange ticker
    status              Open or Closed status
    ==================  ===============================

    """

    COLUMNS = [
        "date", "contract_id", "client_account_id", "instrument_id",
        "type", "currency", "price_date", "price", "units", "value"]
    COLUMNS_EXTRA = [
        "model_portfolio_id", "model_ticker", "isin", "ticker", "status"]
    KEY_COLUMNS = ["date", "client_account_id", "instrument_id"]
    FLOAT_COLUMNS = ["price", "units", "value"]

    def __init__(self, data: pd.DataFrame, merged:bool=False) -> None:
        """Initialization."""
        # Check data is not empty
        if data.empty:
            raise ValueError("Unexpected empty data argument.")
        super().__init__(data, merged)

    def data_mods(self):
        """Modifications to the data before it is passed to the DataFrame."""
        super().data_mods()
        # Convert dates to datetime
        self.data["price_date"] = pd.to_datetime(self.data["price_date"])

    def check(self):
        """Run tests on data and report True of Ok."""
        if not isinstance(self.data, pd.DataFrame):
            raise ValueError("Response is not a DataFrame")
        if self.data.empty:
            raise ValueError("Response is empty.")
        if not self.merged:
            if self.data.columns.to_list() != self.COLUMNS:
                raise ValueError("Unexpected columns in response DataFrame.")
        else:
            if self.data.columns.to_list() != self.COLUMNS + self.COLUMNS_EXTRA:
                raise ValueError("Unexpected columns in response DataFrame.")
        if self.data.duplicated(subset=self.KEY_COLUMNS).any():
            raise ValueError("Non-unique by KEY_COLUMNS attribute.")
        # TODO: Test that one-to-many relationships hold
        # Test for the date column skipping days
        if self.data.date.nunique() > 1:
            # Calculate the date differences. The first difference will always
            # be NaT and is set to one to make this work even for only one date.
            unique_dates = self.data.date.drop_duplicates()
            date_diff = unique_dates.diff()
            date_diff.iloc[0] = datetime.timedelta(days=1)
            # Check that the date differences are all 1
            if not date_diff.dt.days.eq(1).all():
                raise ValueError("Date column has missing days.")
        # Test dtypes
        for column in self.FLOAT_COLUMNS:
            if self.data[column].dtype != float:
                raise ValueError(f"Positions column {column} is not of type float.")

    def merge(self, models: ModelsFrame, instruments: InstrumentsFrame, investors: InvestorsFrame):
        """Merge positions with models, instruments and investors."""
        # Check arguments types
        if not isinstance(models, ModelsFrame):
            raise ValueError("Models argument is not a ModelsFrame object.")
        if not isinstance(instruments, InstrumentsFrame):
            raise ValueError("Instruments argument is not an InstrumentsFrame object.")
        if not isinstance(investors, InvestorsFrame):
            raise ValueError("Investors argument is not an InvestorsFrame object.")

        # Select only the columns needed for the merge
        models = models.data[["model_portfolio_id", "model_ticker"]].drop_duplicates()
        instruments = instruments.data[["instrument_id", "isin", "ticker", "currency", "status"]].drop_duplicates()
        investors = investors.data[["client_account_id", "model_portfolio_id"]].drop_duplicates()


        # Merge investors into positions table
        positions_df = pd.DataFrame.merge(
            self.data,
            investors,
            on=["client_account_id"],
            how="left",
            )
        # Test merge for orphaned positions by client_account_id
        if positions_df["model_portfolio_id"].isnull().any():
            raise ValueError(
                "Orphaned positions by client_account_id in positions table. "
                "Not all investor accounts in positions table are in investors table.")

        # Merge models into positions table
        positions_df = pd.DataFrame.merge(
            positions_df,
            models,
            on="model_portfolio_id",
            how="left",
            )
        # Test merge for orphaned positions by model_portfolio_id
        if positions_df["model_ticker"].isnull().any():
            raise ValueError(
                "Orphaned positions by model_portfolio_id in positions table. "
                "Not all models in positions table are in models table.")

        # Merge instruments into positions table
        positions_df = pd.DataFrame.merge(
            positions_df,
            instruments,
            on="instrument_id",
            how="left",
            )
        # Test merge for orphaned positions by instrument_id
        if positions_df["isin"].isnull().any():
            raise ValueError(
                "Orphaned positions by instrument_id in positions table. "
                "Not all instruments in positions table are in instruments table.")

        # Fix the currency columns names causes by the merge operations
        positions_df = positions_df.rename(columns={"currency_x": "currency"})
        positions_df = positions_df.drop(columns=["currency_y"])

        # Return the merged table with the correct type
        self.data = positions_df
        self.merged = True


class TransactionsFrame(TimeSeriesFrame):
    """Encapsulation of investor account transaction data with built in checking.

    Parameters
    ----------
    json_list : list
        A list of dictionaries containing transaction data.

    The encapsulated table's rows are unique by the `transaction_id`. Note that
    there may be multiple transaction wit the same `date`, `client_account_id`
    and `instrument_id`. Columns:

    ==================  ===============================
    Column Name         Description
    ==================  ===============================
    date                Positions date yyyy-mm-dd
    transaction_id      Finworks transaction id
    contract_id         Finworks contract id
    client_account_id   Client portfolio account unique id
    instrument_id       Finworks instrument id
    is_cashflow         Yes | No
    type                Finworks categories
    sub_type            Finworks categories
    currency            ISO 3-letter currency code
    price               price in currency units
    units               Number of units held
    value               Priced value of units held
    processed_date      Date of transaction processing
    description         English description of transaction
    ==================  ===============================

    If the `merged` flag is True then the following columns are also present:

    ==================  ===============================
    Column Name         Description
    ==================  ===============================
    model_portfolio_id  Model portfolio id
    model_ticker        Our unique model ticker
    isin                Security ISIN Number
    ticker              Exchange ticker
    status              Open or Closed status
    ==================  ===============================

    """
    COLUMNS = [
        "date", "transaction_id",
        "contract_id", "client_account_id", "instrument_id",
        "is_cashflow", "type", "sub_type",
        "currency", "price", "units", "value",
        "processed_date", "description", ]
    COLUMNS_EXTRA = [
        "model_portfolio_id", "model_ticker", "isin", "ticker", "status"]
    KEY_COLUMNS = ["transaction_id"]
    FLOAT_COLUMNS = ["price", "units", "value"]

    def __init__(self, data: pd.DataFrame, merged:bool=False) -> None:
        """Initialization."""
        super().__init__(data, merged)

    def data_mods(self):
        """Modifications to the data before it is passed to the DataFrame."""
        super().data_mods()
        # Convert dates to datetime
        if not self.data.empty:
            self.data["processed_date"] = pd.to_datetime(self.data["processed_date"])
        # Convert float columns to float as this is an issue when an empty data
        # object is constructed and returned.
        if self.empty:
            for column in self.FLOAT_COLUMNS:
                self.data[column] = self.data[column].astype(float)

    def check(self):
        """Run tests on data and report True of Ok."""
        if not isinstance(self.data, pd.DataFrame):
            raise ValueError("Response is not a DataFrame")
        # Do not test for empty. Transactions may be empty. If empty there is
        # nothing further to check on.
        if self.data.empty:
            pass  # Okay to be no transactions
        if not self.merged:
            if self.data.columns.to_list() != self.COLUMNS:
                raise ValueError("Unexpected columns in response DataFrame.")
        else:
            if self.data.columns.to_list() != self.COLUMNS + self.COLUMNS_EXTRA:
                raise ValueError("Unexpected columns in response DataFrame.")
        if self.data.duplicated(subset=self.KEY_COLUMNS).any():
            raise ValueError("Non-unique by KEY_COLUMNS attribute.")
        # Test dtypes
        for column in self.FLOAT_COLUMNS:
            if self.data[column].dtype != float:
                raise ValueError(f"Transactions column {column} is not of type float.")

        # TODO: Test one-to-many relationships

    def merge(self, models: ModelsFrame, instruments:InstrumentsFrame, investors:InvestorsFrame):
        """Merge transactions with models, instruments and investors."""
        # Check arguments types
        if not isinstance(models, ModelsFrame):
            raise ValueError("Models argument is not a ModelsFrame object.")
        if not isinstance(instruments, InstrumentsFrame):
            raise ValueError("Instruments argument is not an InstrumentsFrame object.")
        if not isinstance(investors, InvestorsFrame):
            raise ValueError("Investors argument is not an InvestorsFrame object.")

        # Do not process empty DataFrame
        if self.empty:
            # Add the extra columns to the empty data frame
            if self.merged:
                columns = self.COLUMNS + self.COLUMNS_EXTRA
                self.data = pd.DataFrame(columns=columns)
                self.data = self.data[columns]  # Sort or fail

        # Select only the columns needed for the merge
        models = models.data[["model_portfolio_id", "model_ticker"]].drop_duplicates()
        instruments = instruments.data[["instrument_id", "isin", "ticker", "currency", "status"]].drop_duplicates()
        investors = investors.data[["client_account_id", "model_portfolio_id"]].drop_duplicates()

        # Merge investors ino transactions table
        transactions_df = pd.DataFrame.merge(
            self.data,
            investors,
            on=["client_account_id"],
            how="left",
            )
        # Test merge for orphaned transactions by client_account_id
        if transactions_df["model_portfolio_id"].isnull().any():
            raise ValueError(
                "Orphaned transactions by client_account_id in transactions table. "
                "Not all investor accounts in transactions table are in investors table.")

        # Merge models into transactions table
        transactions_df = pd.DataFrame.merge(
            transactions_df,
            models,
            on="model_portfolio_id",
            how="left",
            )
        # Test merge for orphaned transactions by model_portfolio_id
        if transactions_df["model_ticker"].isnull().any():
            raise ValueError(
                "Orphaned transactions by model_portfolio_id in transactions table. "
                "Not all models in transactions table are in models table.")

        # Merge instruments into transactions table
        transactions_df = pd.DataFrame.merge(
            transactions_df,
            instruments,
            on="instrument_id",
            how="left",
            )
        # Test merge for orphaned transactions by instrument_id
        if transactions_df["isin"].isnull().any():
            raise ValueError(
                "Orphaned transactions by instrument_id in transactions table. "
                "Not all instruments in transactions table are in instruments table.")

        # Fix the currency columns names causes by the merge operations
        transactions_df = transactions_df.rename(columns={"currency_x": "currency"})
        transactions_df = transactions_df.drop(columns=["currency_y"])

        # Return the merged table with the correct type
        self.data = transactions_df
        self.merged = True

    def spanned_by(self, positions: PositionsFrame):
        """Check that positions dates span transactions dates."""
        positions = positions.data
        transactions = self.data
        if not transactions.empty:
            p_min, p_max = positions.date.min(), positions.date.max()
            t_min, t_max = transactions.date.min(), transactions.date.max()
            assert (p_min <= t_min) and (
                t_max <= p_max
            ), "The positions dates do not span transactions dates."


class CollectJSONResponses(object):
    """Use the APISessionManager class to dump JSON responses to text files.

    Intended for collecting test samples of JSON responses from the API.

    Parameters
    ----------
    date : datetime.date, optional
        The date on which to collect the data. If None then the default date
        module constant TEST_DATE is used. Defaults to None.
    simple : bool, optional
        If True then keep only the first N JSON items in each response where N
        is the `number` argument. If False then keep all items in each response
        and ignore the `number` argument. Defaults to False.
    number : int, optional
        The number of item(s) to keep in each response. If `simple` is True then
        this is the number of item(s) to keep. If `simple` is False then this is
        the number is ignored. Defaults to 1.
    basics : bool, optional
        If True then collect basic data. If False then do not collect basics
        data. Defaults to True.
    time_series : bool, optional
        If True then collect time series data. If False then collect only the
        basics data. Defaults to True.
    use_test_data : bool, optional
        If True then use the test data fixtures instead of the API for testing
        and debugging . Defaults to False.
    """

    COLLECTION_DATE = TEST_DATE

    def __init__(
        self, date:datetime.date=None, simple:bool=False, number=1,
        basics:bool=True, time_series:bool=True, use_test_data=False) -> None:
        """Initialization."""
        if basics is False and time_series is False:
            raise ValueError("Both basics and time_series cannot be False.")

        # For testing and debugging use the test fixtures instead of the API
        self.use_test_data = use_test_data
        #  Date on which there should be transactions too
        if time_series is False:
            self.collection_date = None
        elif date is None:
            self.collection_date = self.COLLECTION_DATE
        else:
            self.collection_date = date

        if basics is True:
            logger.info("Collecting basic data.")
        if time_series is True:
            logger.info(
                f"Collecting time series data for date {self.collection_date}.")

        # Collect data lists
        models, instruments, investors, positions, transactions = self.collect(
            basics, time_series)

        # Convert to json strings and dump to JSON text files with pretty
        # formatting.
        if basics:
            if models is not None:
                if simple:
                    models = models[0:number]
                models_json = json.dumps(models, indent=4)
                models_path = get_output_path("models.json")
                with open(models_path, "w") as f:
                    f.write(models_json)
                    logger.info(f"Wrote {len(models)} item(s) to {models_path}.")
            else:
                logger.warning("No models data received.")

            if instruments is not None:
                if simple:
                    instruments = instruments[0:number]
                instruments_json = json.dumps(instruments, indent=4)
                instruments_path = get_output_path("instruments.json")
                with open(instruments_path, "w") as f:
                    f.write(instruments_json)
                    logger.info(f"Wrote {len(instruments)} item(s) to {instruments_path}.")
            else:
                logger.warning("No instruments data received.")

            if investors is not None:
                if simple:
                    investors = investors[0:number]
                investors_json = json.dumps(investors, indent=4)
                investors_path = get_output_path("investors.json")
                with open(investors_path, "w") as f:
                    f.write(investors_json)
                    logger.info(f"Wrote {len(investors)} item(s) to {investors_path}.")
            else:
                logger.warning("No investors data received.")

        # Convert to json strings and dump to JSON text files with pretty
        # formatting.
        if time_series:
            if positions is not None:
                if simple:
                    positions = positions[0:number]
                positions_json = json.dumps(positions, indent=4)
                date_string = self.collection_date.strftime("%Y-%m-%d")
                positions_path = get_output_path(f"positions-{date_string}.json")
                with open(positions_path, "w") as f:
                    f.write(positions_json)
                    logger.info(f"Wrote {len(positions)} item(s) to {positions_path}.")
            else:
                logger.warning("No positions data received.")

            if transactions is not None:
                if simple:
                    transactions = transactions[0:number]
                transactions_json = json.dumps(transactions, indent=4)
                transactions_path = get_output_path(f"transactions-{date_string}.json")
                with open(transactions_path, "w") as f:
                    f.write(transactions_json)
                    logger.info(f"Wrote {len(transactions)} item(s) to {transactions_path}.")
            else:
                logger.warning("No transactions data received.")

        # Log warning of data loss
        if simple:
            logger.warning(f"Kept only first {number} item(s) in each list.")

    def collect(self, basics, time_series):
        """Collect JSON responses as strings."""
        api_client = APIClient()

        # Set default empty dataframes
        models = pd.DataFrame()
        instruments = pd.DataFrame()
        investors = pd.DataFrame()
        positions = pd.DataFrame()
        transactions = pd.DataFrame()
        # Fetch data
        if basics is True:
            api_client.add_task(ModelsTask)
            api_client.add_task(InstrumentsTask)
            api_client.add_task(InvestorsTask)
            results_list = api_client.fetch(return_tasks=True)
            results_list = [result.json_records for result in results_list]
            models, instruments, investors = results_list
        if time_series is True:
            api_client.add_task(PositionsTask, date=self.collection_date)
            api_client.add_task(TransactionsTask, date=self.collection_date)
            results_list = api_client.fetch(return_tasks=True)
            results_list = [result.json_records for result in results_list]
            positions, transactions = results_list

        return models, instruments, investors, positions, transactions

    @staticmethod
    def run(from_date:datetime.date, to_date:datetime.date, use_test_data=False):
        """Collect data over a date range.

        Parameters
        ----------
        from_date : datetime.date
            The start date of the date range.
        to_date : datetime.date
            The end date of the date range.
        use_test_data : bool, optional
            If True then use test fixtures data. Else call the API. Defaults to
            False.

        """
        # Sanity check dates
        from_date, to_date = check_dates(from_date, to_date)

        # Collect basics data
        CollectJSONResponses(time_series=False, use_test_data=use_test_data)

        # Collect time series data for the daily date range between from_date
        # and to_date.
        date_range = pd.date_range(from_date, to_date, freq="D")
        for date in date_range:
            CollectJSONResponses(
                date=date.date(), basics=False, use_test_data=use_test_data)


class Data(object):
    """Package models, instruments, investors, positions, transactions.

    There are categories of data encapsulated in this class:
    1. `basics-data` - models, instruments, investors
    2. `time-series` - positions, transactions

    The `basics-data` is the `models`, `instruments`, `investors`, none of which
    have date columns and are therefore not time-series. The `time-series` data
    are `positions` and `transactions` which have date columns and are therefore
    time-series.

    At class initialization the following are performed:

    TODO: Not true
    - Remove bloating entries with zero units.
    - Check for duplicates by unique key columns and sort by that key.
    - Check `positions` data for skipped days.
    - Checking `positions` dates span `transactions` dates.
    - Dates are converted to ``pandas.DatetimeIndex``
    - Reset each index to its default integer index.

    Parameters
    ----------
    models : pandas.DataFrame
        See the ``ModelsFrame`` class.
    instruments : pandas.DataFrame
        See the ``InstrumentsFrame`` class.
    investors : pandas.DataFrame
        See the ``InvestorsFrame`` class.
    positions : pandas.DataFrame
        See the ``PositionsFrame`` class.
    transactions : pandas.DataFrame
        See the ``TransactionsFrame`` class.
    verify_integrity : bool, optional
        If `True` (default) then check tables and their key columns for:

            TODO: Insert here
            - Check 1
            - Check 2
            ...

    sort_by_keys : bool, optional
        If `True` (default) then sort tables by their key columns.

    The data columns of each attribute are shown in the tables below. Symbols
    such as `+` or `-` denote a group of key columns.

    """

    def __init__(
        self, models, instruments, investors, positions, transactions,
        verify_integrity=True) -> None:
        """Initialization."""
        # Check types
        if not isinstance(models, pd.DataFrame):
            raise ValueError("Expected the models argument to be a pandas.DataFrame object.")
        if not isinstance(instruments, pd.DataFrame):
            raise ValueError("Expected the instruments argument to be a pandas.DataFrame object.")
        if not isinstance(investors, pd.DataFrame):
            raise ValueError("Expected the investors argument to be a pandas.DataFrame object.")
        if not isinstance(positions, pd.DataFrame):
            raise ValueError("Expected the positions argument to be a pandas.DataFrame object.")
        if not isinstance(transactions, pd.DataFrame):
            raise ValueError("Expected the transactions argument to be a pandas.DataFrame object.")

        # Check table key integrity by co-opting the BaseFrame subclasses
        if verify_integrity:
            models = ModelsFrame(models, merged=True, normalized=True)
            instruments = InstrumentsFrame(instruments)
            investors = InvestorsFrame(investors, merged=True)
            positions = PositionsFrame(positions, merged=True)
            transactions = TransactionsFrame(transactions, merged=True)
            transactions.spanned_by(positions)
            #
            self.models = models.data
            self.instruments = instruments.data
            self.investors = investors.data
            self.positions = positions.data
            self.transactions = transactions.data
        else:
            self.models = models
            self.instruments = instruments
            self.investors = investors
            self.positions = positions
            self.transactions = transactions

    def __str__(self):
        """Return the informal string output. Interchangeable with str(x)."""
        models = self.models.tail().__str__()
        instruments = self.instruments.tail().__str__()
        investors = self.investors.tail().__str__()
        positions = self.positions.tail().__str__()
        transactions = self.transactions.tail().__str__()
        return (
            f"Models:\n{models}\n\n"
            f"Instruments:\n{instruments}\n\n"
            f"Investors:\n{investors}\n\n"
            f"Positions:\n{positions}\n\n"
            f"Transactions:\n{transactions}\n\n"
        )

    @property
    def empty(self):
        """Returns `True` when positions are empty."""
        return self.positions.empty

    def slice(self, from_date=None, to_date=None):
        """Slice the time-series data components of [from_date, to_date].

        If an argument is `None` then that end of the slice is open ended
        (similarly to using the `:` slicing symbol).
        """
        # Slice the time-series data components in the inclusive range
        # [from_dat, to_date]
        self.positions = self.positions[(from_date <= self.positions.date.dt.date) & (self.positions.date.dt.date <= to_date)]
        if not self.transactions.empty:
            self.transactions = self.transactions[(from_date <= self.transactions.date.dt.date) & (self.transactions.date.dt.date <= to_date)]

    def update(self, new):
        """Update original data with new data.

        Parameters
        ----------
        new : Data
            The data that will replace the original data

        Returns
        -------
        Data
            Original data updated with data form the `new` argument.

        Any existing time-series rows in the cache will be updated with the
        time-series rows in the `new` argument. All time-series rows in the
        `new` argument which are not in the cache will be added. Dataframe rows
        are uniquely identified by their key columns columns.

        Current time-series data attributes `positions` and `transactions` are
        updated with the attributes of the `new` argument, but the basics-data
        attributes `models`, `instruments` and `investors` of the `new` data
        overwrite current basics-data.

        See also
        --------
        .POSITIONS_KEYS
        .TRANSACTIONS_KEYS

        """
        # Update the positions using the PositionsFrame update method and
        # convert back to pandas DataFame. Note that the columns are merged
        # columns
        positions = PositionsFrame(self.positions, True)
        positions_new = PositionsFrame(new.positions, True)
        positions.update(positions_new)

        transactions = TransactionsFrame(self.transactions, True)
        transactions_new = TransactionsFrame(new.transactions, True)
        transactions.update(transactions_new)

        # Return a newly constructed and verified object
        return Data(
            new.models, new.instruments, new.investors,
            positions.data, transactions.data,
            verify_integrity=True,
        )

    def date_range(self):
        """The first and last dates in the `positions` time-series data.

        Returns
        -------
        datetime.date
            The first date in the `positions` time-series data `date` column.
        datetime.date
            The last date in the `positions` time-series data `date` column.

        """
        all_dates = self.positions.date
        from_date, to_date = all_dates.min(), all_dates.max()

        # Return datetime.date objects
        return from_date.date(), to_date.date()

    def iter_periods(self):
        """Iterator over data time-series components in ISO weekly blocks.

        Yields
        ------
        int
            The data block year.
        int
            The data block ISO week number.
        Data
            The data block an ISO week long (Monday to Sunday). The first and/or
            the last block may be partially full.
        """
        # Add year and week columns - ISO 8601 specification
        if not self.positions.empty:
            positions = pd.concat(
                [self.positions, self.positions.date.dt.isocalendar()], axis="columns"
            )
            # DEBUG: Collect dates, days, log data, drop dates, days afterward
            positions_info = positions[["date", "year", "week", "day"]].drop_duplicates(
                ["year", "week"]
            )
            positions_info.drop(columns=["date", "day"], inplace=True)
        else:
            # Assign empty for easy concatenation below
            positions_info = self.positions

        # Add year and week columns - ISO 8601 specification
        if not self.transactions.empty:
            transactions = pd.concat(
                [self.transactions, self.transactions.date.dt.isocalendar()],
                axis="columns",
            )
            # DEBUG: Collect dates, days, log data, drop dates, days afterward
            transactions_info = transactions[
                ["date", "year", "week", "day"]
            ].drop_duplicates(["year", "week"])
            transactions_info.drop(columns=["date", "day"], inplace=True)
        else:
            # Assign empty for easy concatenation below
            transactions_info = self.transactions

        # Amalgamate years and week of positions and transactions
        periods = pd.concat([positions_info, transactions_info]).drop_duplicates()

        # Create generator
        for _, row in periods.iterrows():
            year = row.year
            week = row.week
            if not self.positions.empty:
                positions_selected = positions[
                    (positions.year == year) & (positions.week == week)
                ].drop(columns=["year", "week", "day"])
            else:
                positions_selected = self.positions
            if not self.transactions.empty:
                transactions_selected = transactions[
                    (transactions.year == year) & (transactions.week == week)
                ].drop(columns=["year", "week", "day"])
            else:
                transactions_selected = self.transactions
            # Construct a new object with selections
            data = Data(
                self.models,
                self.instruments,
                self.investors,
                positions_selected,
                transactions_selected,
            )

            # Yield iterator data items
            yield year, week, data

    def get_last_data(self):
        """Get the last dated data of the instance.

        The `positions` last date is taken as the last date. This is because
        some days there are no transactions, whereas there are positions
        every day.
        """
        last_date = self.positions.date.max()
        positions = self.positions[self.positions.date == last_date]
        transactions = self.transactions[self.transactions.date == last_date]
        # Construct a new object with selections
        data = Data(
            self.models, self.instruments, self.investors, positions, transactions
        )

        return data

    def last_date(self):
        """Get the last date of the positions time-series data.

        This is determined from the last date of the positions component of the
        time-series data.

        Return
        ------
        datetime.date
            The last date of the positions component of the time-series data.
        """
        return self.positions.date.max().to_pydatetime().date()

    def get_tuple(self):
        """Return models, instruments, investors, positions, transactions."""
        return (
            self.models,
            self.instruments,
            self.investors,
            self.positions,
            self.transactions,
        )

    @staticmethod
    def concat(data_list, verify_integrity=True):
        """Concatenate a list of ``Data`` objects.

        The `models`, `instruments` and `positions` attributes (known as basics
        data) of the last ``Data`` object in the `data_list` argument shall
        overwrite (be prioritized over) those of the previous ``Data`` items,
        i.e., no concatenation! This is because when using a list of ``Data``
        items in the `data_list` argument which are ranked by increasing date to
        prioritize the most recent or most fresh basics-data.

        The time-series data `positions` and `transactions` are concatenated.

        Parameter
        ---------
        data_list : list
            List of ``Data`` items.
        check_days: bool, optional
            If False then skip the check for skipped days in the `positions`
            data. This is useful for working to repair the `Data` object.
        verify_integrity : bool, optional
            If `True` then check tables and their key columns for:

                - have correct columns
                - have no duplicates
                - have cross reference integrity
                - have no skipped position days
                - positions dates span transactions dates

        Returns
        -------
        Data:
            Concatenated positions and transactions

        """
        # For the basics data always prioritize the last Data object in the list
        # as containing the most up-to-date data.
        last_data = data_list[-1]
        # From the list of `Data` objects unzip a list of positions and a list
        # of transactions.
        positions_list, transactions_list = list(
            zip(*[(item.positions, item.transactions) for item in data_list])
        )

        # Concatenate lists
        positions = pd.concat(positions_list)
        transactions = pd.concat(transactions_list)

        # Return a new object with the concatenated data and check the new
        # object for integrity and sorted by key columns.
        return Data(
            # Use last data's basics-data
            last_data.models,
            last_data.instruments,
            last_data.investors,
            # Use concatenated time-series data
            positions,
            transactions,
            # Always verify integrity
            verify_integrity=verify_integrity,
        )

    @staticmethod
    def iter_concat(iterator, **kwargs):
        """Concatenate a list of ``Data`` objects using am iterator.

        The iterator must yield ``Data`` objects which will shall then be
        concatenated into a single ``Data`` object. Iteration is used to avoid
        memory overflow issues.

        Note
        ----
        The `models`, `instruments` and `positions` attributes (know as
        basics-data) of the first ``Data`` object in the list shall
        overwrite (be prioritized over) those of the subsequent ``Data``
        items. It is therefore a good idea when using a list of ``Data``
        items which are ranked by date of caching to first reverse the rank
        to prioritize the most recent basics-data.

        Parameters
        ----------
        iterator : yield method
            Yields one ``Data`` object at a time.
        **kwargs :
            The iterator arguments if any.

        See also
        --------
        concat
        """
        # Produce and empty DataFrames for extension by iteration
        first = True
        positions = pd.DataFrame()
        transactions = pd.DataFrame()
        for data in iterator(**kwargs):
            if first:
                # Keep only first Data object's basic data
                models, instruments, investors = (
                    data.models,
                    data.instruments,
                    data.investors,
                )
                first = False  # Reset to block this segment hereafter
            # Concatenate lists dropping duplicates
            positions = pd.concat(
                [positions, data.positions], axis="index", ignore_index=True
            )
            transactions = pd.concat(
                [transactions, data.transactions], axis="index", ignore_index=True
            )

        # Return a new object with the concatenated data and verify integrity of
        # new object
        return Data(
            models,
            instruments,
            investors,
            positions,
            transactions,
            verify_integrity=True,
        )

    @staticmethod
    def assert_equal(data: Data, other:Data) -> None:
        """Assert that two Data objects are equal."""
        assert_frame_equal(data.models, other.models)
        assert_frame_equal(data.instruments, other.instruments)
        assert_frame_equal(data.investors, other.investors)
        assert_frame_equal(data.positions, other.positions)
        assert_frame_equal(data.transactions, other.transactions)


class ClientInterface(object):
    """Useful APIClient interface methods.

    Parameters
    ----------
    test_url : str, optional
        The URL of the test server. If provided then the API client will use
        this URL instead of the default URL.

    This if for users wishing to avoid `async with` statements and wish to
    simply access the API data directly.

    Uses the same-named, async ``APIPaths`` class methods for fetching data.
    """

    def __init__(self, test_url: str=None) -> None:
        """Initialization."""
        if test_url:
            self.api_client = APIClient(test_url)
        else:
            self.api_client = APIClient()

    def get_models(self):
        """List the available models on the system linked to the Model Manager.

        Returns
        -------
        ModelsFrame
            The model instrument weights
        """
        # Add task to the API client and fetch the single result in the  data
        # list
        self.api_client.add_task(ModelsTask)
        data_list = self.api_client.fetch()
        return data_list[0]

    def get_instruments(self):
        """List the details of instruments.

        Returns
        -------
        InstrumentsFrame
            Details of instruments available on the system.
        """
        # Add task to the API client and fetch the single result in the  data
        # list
        self.api_client.add_task(InstrumentsTask)
        data_list = self.api_client.fetch()
        return data_list[0]

    def get_investors(self):
        """List all investor accounts that are invested in Model Portfolios

        Returns
        -------
        InvestorsFrame
            Investor contracts and accounts.
         """
        # Add task to the API client and fetch the single result in the  data
        # list
        self.api_client.add_task(InvestorsTask)
        data_list = self.api_client.fetch()
        return data_list[0]

    def get_positions(self, date):
        """List the Investor accounts underlying holdings and values values.

        Parameters
        ----------
        date : datetime.date
            Date on which positions are required. Note that data will run until
            close of the day so _today_ will not be available until after day
            close, probably closer to midnight. If the argument is not
            provided then the date will default to today.

       Returns
        -------
        PositionsFrame
            Investor account positions
         """
        # Add task to the API client and fetch the single result in the  data
        # list
        self.api_client.add_task(PositionsTask, date=date)
        data_list = self.api_client.fetch()
        return data_list[0]

    def get_transactions(self, date):
        """List the investors account transactions.

        Parameters
        ----------
        date : datetime.date
            Date on which transactions are required. Note that data will run
            until close of the day so _today_ will not be available until after
            day close, probably closer to midnight. If the argument is not
            provided then the date will default to today.

        Returns
        -------
        TransactionsFrame
            Investor account transactions
        """
        # Add task to the API client and fetch the single result in the  data
        # list
        self.api_client.add_task(TransactionsTask, date=date)
        data_list = self.api_client.fetch()
        return data_list[0]

    def get_basics_data(self):
        """Get the latest Finworks models, instruments & investors.

        Returns
        -------
        ModelsFrame
            The model instrument weights
        InstrumentsFrame
            Details of instruments available on the system.
        InvestorsFrame
            Investor contracts and accounts.
        """
        # Add task to the API client and fetch the single result in the  data
        # list
        self.api_client.add_task(ModelsTask)
        self.api_client.add_task(InstrumentsTask)
        self.api_client.add_task(InvestorsTask)
        data_list = self.api_client.fetch()
        return data_list[0], data_list[1], data_list[2]

    def get_time_series(self, date=None, from_date=None, to_date=None):
        """Generate list of async get tasks, one per day, in the date range.

        Parameters
        ----------
        date : datetime.date, optional
            Date on which positions and transactions are required. Note that if
            this argument is provided then the `from_date` and `to_date`
            arguments are ignored and the `from_date` and `to_date` are set to
            the same date as the `date` argument.
        from_date : datetime.date
            Date from when, and including, when transaction are required.
            If none provided the date shall default to 1900-01-01.
        to_date : datetime.date
            Date to, and including, when transaction are required. Note that
            data will run until close of the day so _today_ will not be
            available until after day close, probably closer to midnight.
            If none provided the date shall default to today.

        Warning
        -------
        Finworks will ot return more than two weeks deep of data so be careful
        with the use of `from_date` and `to_date` arguments.

        Returns
        -------
        PositionsFrame
            Investor account positions
        TransactionsFrame
            Investor account transactions
        """
        # Check date arguments
        if date is not None:
            from_date = date
            to_date = date
        else:
            if not from_date or not to_date:
                raise ValueError(
                    "Either date or both from_date and to_date must be provided.")

        # Sanity check dates
        from_date, to_date = check_dates(from_date, to_date)

        # Generate a list of dates between from_date and to_date
        delta = to_date - from_date
        date_list = [
            from_date + datetime.timedelta(days=i) for i in range(delta.days + 1)
        ]

        # Add a list of task, one for each date in the date_list
        for date in date_list:
            self.api_client.add_task(PositionsTask, date=date)
            self.api_client.add_task(TransactionsTask, date=date)

        # Run all tasks
        results_list = self.api_client.fetch()

        # De-interleave daily holdings and transactions
        positions_list = list()
        transactions_list = list()
        for _ in date_list:
            positions_list.append(results_list.pop(0))
            transactions_list.append(results_list.pop(0))

        # Concatenate results
        positions = PositionsFrame.concat(positions_list)
        transactions = TransactionsFrame.concat(transactions_list)

        return positions, transactions

    def get_data(self, date=None, from_date=None, to_date=None, verify_integrity=True):
        """Fetch all data in date range and format to an internal standard.

        Warning
        -------
        Do not use positional arguments with this method. Use keyword arguments
        only or the method could misinterpret the arguments!

        Parameters
        ----------
        date : datetime.date, optional
            Date on which positions and transactions are required. Note that if
            this argument is provided then the `from_date` and `to_date`
            arguments are ignored and the `from_date` and `to_date` are set to
            the same date as the `date` argument.
        from_date : datetime.date
            Date from when, and including, when transaction are required.
            If none provided the date shall default to 1900-01-01.
        to_date : datetime.date
            Date to, and including, when transaction are required. Note that
            data will run until close of the day so _today_ will not be
            available until after day close, probably closer to midnight.
            If none provided the date shall default to today.
        verify_integrity : bool
            If True, then check that the data is consistent and complete. If
            False, skip the integrity check. Skipping the integrity check can
            improve performance but may result in inconsistent or incomplete
            data. Please see the ``Data`` class docstring for the integrity
            checks performed.

        Return
        ------
        Data
            API data packaged in a ``Data`` object. See the ``Data` class
            docstring for the data formats. See the ``Data`` class docstring for
            the columns of the data items.

        See also
        --------
        Data
        """
        # Check date arguments
        if date is not None:
            from_date = date
            to_date = date
        else:
            if not from_date or not to_date:
                raise ValueError(
                    "Either date or both from_date and to_date must be provided.")

        # Sanity check dates
        from_date, to_date = check_dates(from_date, to_date)

        # Generate a list of dates between from_date and to_date
        delta = to_date - from_date
        date_list = [
            from_date + datetime.timedelta(days=i) for i in range(delta.days + 1)
        ]

        # Add get basics data tasks
        self.api_client.add_task(ModelsTask)
        self.api_client.add_task(InstrumentsTask)
        self.api_client.add_task(InvestorsTask)

        # Add a list of get time-series tasks, one for each date in the
        # date_list
        for date in date_list:
            self.api_client.add_task(PositionsTask, date=date)
            self.api_client.add_task(TransactionsTask, date=date)

        # Run all tasks
        results_list = self.api_client.fetch()

        # Pop off basics data
        models = results_list.pop(0)
        instruments = results_list.pop(0)
        investors = results_list.pop(0)

        # De-interleave by popping off daily holdings and transactions
        positions_list = list()
        transactions_list = list()
        for _ in date_list:
            positions_list.append(results_list.pop(0))
            transactions_list.append(results_list.pop(0))

        for transactions in transactions_list:
            assert transactions.data.price.dtype == 'float64', "Expected a float price."

        # Concatenate results
        positions = PositionsFrame.concat(positions_list)
        transactions = TransactionsFrame.concat(transactions_list)
        assert transactions.data.price.dtype == 'float', "Expected a float price."

        # Assert result class types
        assert isinstance(models, ModelsFrame), "ModelsFrame expected."
        assert isinstance(instruments, InstrumentsFrame), "InstrumentsFrame expected."
        assert isinstance(investors, InvestorsFrame), "InvestorsFrame expected."
        assert isinstance(positions, PositionsFrame), "PositionsFrame expected."
        assert isinstance(transactions, TransactionsFrame), "TransactionsFrame expected."

        # Merge models, instruments, investors data to positions and
        # transactions.
        positions.merge(models, instruments, investors)
        transactions.merge(models, instruments, investors)
        # Lastly merge basics-data.
        models.merge(instruments)
        investors.merge(models)

        return Data(
            models.data,
            instruments.data,
            investors.data,
            positions.data,
            transactions.data,
            verify_integrity=verify_integrity,
        )


class Cache(object):
    """Get, integrate and cache ``Data`` objects.

    The ``Data`` object's time-series components are daily sampled and are
    serialised to disk as a series of one ISO-week length blocks written as
    binary `pickle` files called a block file.

    Each weekly pickle file name was appended with the block's week year and ISO
    week number `{_CACHE_FILE}-{year_number}-{iso_week_number}.pkl'. The
    time-series data is updated every time the cache is updated. This may
    involve adding data to an exiting block file or creating a new block file,
    or both. Care is taken that daily sampling is contiguous across block files.

    The ``Data`` object's basics-data components are serialised to disk as one
    file with the latest data written as a binary `pickle` file. The file name
    is 'basics-data.pkl'. The basics-data is updated every time the cache is
    updated.

    The last date of the cache is maintained in a binary pickle file
    `last_date.pkl`. The last date is updated every time the cache is updated.

    Parameters
    ----------
    alt_path : str
        Alternative full cache data path.
    test_url : str
        The URL of the test server. If provided then the API client will use
        this URL instead of the default URL.

    Below are a few months of ISO week blocks generated by the Linux utility
    `ncal`. Install ncal with `sudo apt install ncal`. Then call `man ncal` for
    more on `ncal`. These are useful for understanding the ISO week numbering
    at the early days of the Finworks data:

    ```
        $ ncal -W7 -bwM 8 2021
            August 2021
         w| Mo Tu We Th Fr Sa Su
        30|                    1
        31|  2  3  4  5  6  7  8
        32|  9 10 11 12 13 14 15
        33| 16 17 18 19 20 21 22
        34| 23 24 25 26 27 28 29
        35| 30 31

        $ ncal -W7 -bwM 9 2021
            September 2021
         w| Mo Tu We Th Fr Sa Su
        35|        1  2  3  4  5
        36|  6  7  8  9 10 11 12
        37| 13 14 15 16 17 18 19
        38| 20 21 22 23 24 25 26
        39| 27 28 29 30

            September 2023
         w| Mo Tu We Th Fr Sa Su
        35|              1  2  3
        36|  4  5  6  7  8  9 10
        37| 11 12 13 14 15 16 17
        38| 18 19 20 21 22 23 24
        39| 25 26 27 28 29 30

    ```

    See also
    --------
    Data

    """
    PICKLE_PROTOCOL = 4  # Changing this may invalidate the cache

    # Select cache path based on API domain
    if APIClient.ENVIRONMENT == "test":
        CACHE_PATH = get_data_path("finworks/test_cache")
    elif APIClient.ENVIRONMENT == "production":
        CACHE_PATH = get_data_path("finworks/live_cache")

    TIME_SERIES_FILE = "time-series-data"
    BASICS_DATA_FILE = "basics-data"
    LAST_DATE_FILE = "last-date"

    def __init__(self, alt_path=None, test_url:str=None):
        """Initialization."""
        # Client interface
        if test_url:
            self.client = ClientInterface(test_url)
        else:
            self.client = ClientInterface()

        # Check for alternative cache path argument
        path = os.path.dirname(__loader__.path)  # This module's file path
        if alt_path is not None:
            # Use alternative specified path
            path = alt_path
        else:
            # Use default path
            path = self.CACHE_PATH
        self._path = path
        # Create the path folder if it does not already exist
        self._create_cache_folder(self._path)

    def _create_cache_folder(self, path):
        """Create a cache folder the the path if it does not exist."""
        if not os.path.isdir(path):
            logger.debug(f"Create new cache folder {path}")
            # Recursive directory creation function. Like `mkdir()``, but makes
            # all intermediate-level directories needed to contain the leaf
            # directory.
            os.makedirs(path)

    def _delete(self):
        """Delete all files in the cache.

        Does not delete the folder itself, only all the files.

        Warning
        -------
        This method is dangerous and should be used with caution. It will
        delete all files in the cache folder. Back up the cache folder before
        running this method.

        """
        path = self._path
        logger.warning(f"Deleting all files in cache folder {path}")
        for file_name in os.listdir(path):
            file_path = os.path.join(path, file_name)
            os.remove(file_path)

    def batch_update(self, batch_size=7, batches=None, max_retries=3, roll_back=1):
        """Update in batches with batch retires upon batch failure.

        This method provides a more robust way for downloading large updates
        when the cache last date is far behind the current date. The update is
        broken up into multiple tranches of contiguous, non-overlapping date
        ranges. Each tranche update is called a batch and is a completely
        separate update. Each update will be independently retried if it fails.

        This method calls the ``update`` method with it's argument `increment`
        set to the the `batch-size` argument. Batches of `batch_size` are run
        until the ``is_up_to_date`` attribute becomes `True`.

        Parameters
        ----------
        batch_size : int, optional
            The size of the batch passed as the the `increment` argument of the
            ``update`` method, by default 7
        batches : int, optional
            The number of batches to run. If `None` then the number of batches
            is not considered and the update will run until the cache is up to
            date. If a number is provided then the update will run for that many
            batches, by default `None`
        max_retries : int, optional
            The maximum permitted number of retries for a failed batch , by
            default 4
        roll_back : int, optional
            The number of days (N days) with which to roll back the from_date of
            the API fetch from the cache last date. This is useful for
            overwriting stale cache data. Default is 1 day.

        Raises
        ------
        Exception
            If the maximum number of permissible reties is exceeded then the
            exception that cased the updated is raised.

        See also
        --------
        update
        """
        # FIXME: In batch update the to_date can exceed today and cause an exception.
        retries = 0
        batches = batches if batches else None
        while batches is None or batches > 0:
            try:
                # Log all batch update parameters
                if batches:
                    logger.info(f"Starting a batch update (try={retries}, batch size={batch_size}, batches remaining={batches}, max_retries={max_retries}, roll_back={roll_back}).")
                else:
                    logger.info(f"Starting a batch update (try={retries}, batch size={batch_size}, max_retries={max_retries}, roll_back={roll_back}).")
                # One batch is one update of batch_size days
                self.update(increment=batch_size, roll_back=roll_back)
            except Exception as ex:
                if retries >= max_retries:
                    logger.exception(ex)
                    raise ex
                else:
                    logger.warning("Batch update failed with exceptions.")
                    logger.exception(ex)
                    logger.warning("Retrying.")
                # Batch failed - Increment retry counter
                retries += 1
            else:
                logger.info("Update completed.")
                # Batch success - Reset retry counter and decrement batches
                batches = batches - 1 if batches else None
                retries = 0

            # Break out of batch updates if cache is up to date. Note that the
            # above will already have updated the cache with roll-back.
            if self.is_up_to_date():
                logger.info("Batches completed.")
                break

    def update(self, **kwargs):
        """Update the cache.

        This method implements the logic to determine if the cache should be
        updated or not and if so what date ranges to use. This method uses the
        ``get_api_data`` method to fetch new API data if required and possible.
        It uses the ``write_cache` method to manage data contiguity and
        integrate any new data into the disk cache.

        As this method may be run during the day the computed ``from_date`` for
        updating the cache with API data is rolled back by 1 day. This is to
        overwrite the last day of cache data which by the end of the day or the
        next or later day may contain stale data.
        This is because the last update of the cache may have been in the middle
        of the day and may therefore contain only partial data for the day,
        hence the requirement for overwriting it later on.

        Parameters
        ----------
        to_date : datetime.date, optional
            Date to, and including, when transaction are required. Whe provided
            the `increment` argument will be ignored.
        increment : int, optional
            Use this amount of days added to the cache last date as the to_date.
        force : bool, optional
            If `True` then treat the cache as not fresh and attempt to refresh
            it with the latest data.
        roll_back : int, optional
            The number of days (N days) with which to roll back the
            from_date of the API fetch from the cache last date. This is useful
            for overwriting stale cache data. Default is 1 day.
        data : Data, optional
            A data set to cache. If this object is provided then any cached data
            will be discarded and the cache populated with the data form the
            object. If this object is provided then all the other arguments are
            ignored.
        """
        logger.info("Starting a cache update.")
        # Arguments determine how and over what period the data is sourced
        if "data" in kwargs:
            # Delete the entire cache and replace with the data object. The
            # from_date and to_date are no longer applicable.
            logger.debug("Deleting the entire cache and replacing with new data.")
            data = kwargs.pop("data")
            assert isinstance(data, Data), "Expected a `Data` class object."
            self._delete()
            new_data = data
        else:
            # Now we need API from_date and to_date
            today = datetime.date.today()
            logger.info(f"Today's date is {today}")
            if START_DATE > today:
                raise ValueError(f"The START_DATE {START_DATE} is after today {today}.")
            last_cache_date = self.last_date()
            if last_cache_date is None:
                last_cache_date = START_DATE - datetime.timedelta(days=1)
                logger.info(f"Cache is new. A virtual cache last-date is set one day before START_DATE {last_cache_date}.")
            if last_cache_date > today:
                raise ValueError(f"The last cache date {last_cache_date} is in the future.")
            logger.debug(f"The START_DATE is {START_DATE}.")
            # The API from_date must fall on the day after the cache last-date
            from_date = last_cache_date + datetime.timedelta(days=1)
            logger.info(f"Cache last-date is {last_cache_date} so the from_date is set to {from_date}.")

            # Get the roll_back argument if any and use it to roll back the API
            # from_date
            if "roll_back" in kwargs:
                roll_back = kwargs.pop("roll_back")
            else:
                # Default rolls back the cache date by 1 day to overwrite the
                # last day of cache data which may contain stale data.
                roll_back = 1
            # If the cache is new then cancel the roll back
            if self.last_date() is None:
                logger.debug("Cache is new. Cancelling roll back to zero.")
                roll_back = 0
            from_date = from_date - datetime.timedelta(days=roll_back)
            logger.info(f"The roll_back is set to {roll_back} days so the from_date is rolled back to {from_date}.")
            if today < from_date:
                raise ValueError(f"The from_date {from_date} is after today {today}. Check parameters.")

            # No more mods to from_date allowed from here on.

            # Arguments determine how and over what period the data is sourced
            if 'increment' in kwargs:
                increment = kwargs.pop('increment')
                if increment < 1:
                    raise ValueError("The increment must be at least 1 day.")
                # An increment of 1 day requires the API from_date and to_date
                # to be the same. This will fetch on day of data on the date.
                to_date = last_cache_date + datetime.timedelta(days=increment)
                logger.info(f"The increment is set to {increment} days so the to_date is set to {to_date}.")
                if to_date > today:
                    to_date = today
                    logger.info(f"The to_date is corrected back to today {to_date}.")
            elif 'to_date' in kwargs:
                to_date = kwargs.pop('to_date')
                logger.info(f"The to_date is set by argument to {to_date}.")
            else:
                to_date = today
                logger.info(f"The to_date defaults to today {to_date}.")
            # Trim the to_date to today
            if to_date > today:
                raise ValueError(f"The to_date {to_date} is after today {today}. Check parameters.")

            # Get the required data from the API
            new_data = self.get_api_data(from_date, to_date)

        # Update the cache data (if it exists) with fresh API data
        self.write_cache(new_data)

        # Write last date tracker file and must be last write operation
        last_date = new_data.last_date()
        self.write_last_date(last_date)

    def get_api_data(self, from_date=None, to_date=None):
        """Fetch and return the API data over a date range applying roll-back.

        A roll back argument is provided to overwrite old cache data.

        Parameters
        ----------
        from_date : datetime.date, optional
            Date from when, and including, when transaction updates are
            required. If none provided the date shall default to the
            `Cache.START_DATE`.
        to_date : datetime.date, optional
            Date to, and including, when API data are required. If none provided
            the date shall default to today.
        """
        from_date, to_date = check_dates(from_date, to_date)

        logger.info(
            "Cache is starting API data fetch "
            f"(from_date={from_date}, the to_date={to_date}).")

        # Get fresh API data - careful using positional arguments
        data = self.client.get_data(from_date=from_date, to_date=to_date)
        assert data.transactions.price.dtype == float, "Expected a float price."
        if data.empty:
            raise ValueError("Unexpected API returns empty data.")

        return data

    def is_up_to_date(self, test_date=None):
        """Test if the cache is up-to-date, i.e., the date is today.

        Parameters
        ----------
        test_date : datetime.date, optional
            A date that can be specified as the today date to be tested for in
            place of the default test date of ``datetime.date.today()``.

        Returns
        -------
        bool
            Will be `True` if the cache is up-to-date (today). If the cache is
            empty then the return will be `False`.


        Warning
        -------
        If an ``update`` has been executed in the middle of the day, the cache
        may test as up-to-date, but there may be further transaction as well as
        position changes throughout the rest of the day that are not yet in the
        cache.

        """
        # Default test date is today
        if test_date is None:
            test_date = datetime.date.today()

        last_date = self.last_date()
        if last_date is None:
            return False
        else:
            return last_date >= test_date

    def get_cache_data(self, from_date=None, to_date=None, progress_bar=True):
        """Get cached data over a date range.

        Parameters
        ----------
        from_date : datetime.date
            Inclusive start date of the time-series part of the returned data.
        to_date : datetime.date
            Inclusive last date of the time-series part of the returned data.
        progress_bar : bool, optional
            Whether or not to show the cache data-block, file-read, progress-
            bar.

        Returns
        -------
        Data
            The Finworks data object with the transactions and positions
            time-series over the inclusive range [from_date, to_date].

        See also
        --------
        Data
        """
        from_date, to_date = check_dates(from_date, to_date)

        # Read cache files and concatenate.
        data = self.read_cache(from_date, to_date, progress_bar=progress_bar)
        if data is None:
            raise CacheError("No Cache data in the specified dates range.")

        return data

    def get_last_data(self, last_date: datetime.date = None):
        """Get cached data over a date range.

        Parameters
        ----------
        last_date : datetime.date
            The last date of the time-series part of the returned data. If not
            specified then the last date of the cache is used (see the
            ``get_last_cache_date`` method).

        Returns
        -------
        Data
            The Finworks data object with the transactions and positions
            time-series for today's date.

        Raises
        ------
        CacheError
            If the last date is not in the cache.
        """
        if last_date is None:
            # Get the last available data
            last_date = self.last_date()
        # Check that the last_date is in the cache
        elif not last_date <= self.last_date():
            raise CacheError(
                f"Last date {last_date} is not in the cache. "
                "Please update the cache "
                "or change your last date parameter!"
            )
        data = self.get_cache_data(last_date, last_date)
        if data.empty:
            raise CacheError(
                "Last period of data is unavailable. Please update the cache."
            )

        return data

    def last_date(self):
        """Return the cache last-date file date as a ``datetime.date`` object.

        Return
        ------
        datetime.date
            The last date of the positions component of the time-series data.
            However if the cache is empty then return None.
        """
        path = os.path.join(self._path, f"{self.LAST_DATE_FILE}.pkl")
        if os.path.exists(path):
            with open(path, "rb") as file:
                last_date = pickle.load(file)
                # From pandas.Timestamp to datetime.date
        else:
            # First use, no last date cache file so return None
            last_date = None
        return last_date

    def read_cache(
        self, from_date: datetime.date, to_date: datetime.date,
        models=None, instruments=None, investors=None,
        slice=True,
        progress_bar=True,
    ):
        """Return the cache data over the specified date range.

        from_date : datetime.date
            Inclusive first date of the data.
        to_date : datetime.date
            Inclusive last date of the data.
        models : pandas.DataFrame, optional
            The models data. If not provided then the data is read from the
            cache.
        instruments : pandas.DataFrame, optional
            The instruments data. If not provided then the data is read from the
            cache.
        investors : pandas.DataFrame, optional
            The investors data. If not provided then the data is read from the
            cache.
        slice : bool
            If `True` then the data date range is sliced to be strictly inside
            the specified date range. Else due to the week-long block nature of
            the cache data there may be data "sticking out" on either side of
            the specified date range.
        check_days: bool, optional
            If False then skip the check for skipped days in the `positions`
            data. This is useful for working to repair the `Data` object.
        progress_bar : bool, optional
            Whether or not to show the cache data-block, file-read, progress-
            bar.

        Return
        ------
        Data
            Cache data sliced over the specified date range. See the `slice`
            argument for more information.
        """

        # Return None if the cache is empty which is indicated by the last-date
        # being None.
        if self.last_date() is None:
            logger.debug("Cache is empty.")
            return None

        # Sanity check dates
        from_date, to_date = check_dates(from_date, to_date)

        # Check if basics data is provided as arguments
        if models is not None and instruments is not None and investors is not None:
            # Check that the instruments proxy_isin column is provided
            if "proxy_isin" not in instruments.columns:
                raise ValueError("The instruments data must have a proxy_isin column.")
        elif models is not None or instruments is not None or investors is not None:
            raise ValueError(
                "Inconsistent arguments. If any of the models, instruments "
                "or investors are provided then all must be provided."
            )
        else:
            # Unless models, instruments and investors data are all provided as
            # arguments then read them from the cache.
            models, instruments, investors = self.read_basics_data()

        # Read positions and transactions data from the cache time-series period
        # block files, construct a Data object for the period and append it to a
        # list for concatenation later.
        data_list = list()
        size = len(self.get_num_blocks(from_date, to_date))
        # Show progress bar if desired and read `size` is above a threshold.
        if progress_bar and size > 14:
            generator = tqdm(
                self.iter_read_time_series(from_date, to_date),
                total=size,
                desc="Reading cache files",
                ncols=80,
            )
        else:
            generator = self.iter_read_time_series(from_date, to_date)
        for _, _, positions, transactions in generator:
            assert transactions.price.dtype == float, "Expected a float price."
            data = Data(
                models,
                instruments,
                investors,
                positions,
                transactions,
                # Integrity should be okay as it was checked at write time
                verify_integrity=False,
            )
            data_list.append(data)

        if len(data_list) > 0:
            # Splice all the Data items in the list into one Data object
            data = Data.concat(data_list)
            if slice:
                # Slice to required date range as the cached data is an integer
                # number of one-week sized blocks and so there could be data
                # outside the date range.
                data.slice(from_date, to_date)
            from_date, to_date = data.date_range()
            logger.debug(f"Cache read returning data with the date range [{from_date}, {to_date}].")
            return data
        else:
            # No data found
            logger.warning(f"Cache read NOT returning data with the date range [{from_date}, {to_date}].")
            return None

    def repair(self, from_date=None, to_date=None):
        """Detects and repairs missing data in time-series blocks

        Parameters
        ----------
        from_date : datetime.date
            Inclusive first date of date range.
        to_date : datetime.date
            Inclusive last date of the date range.

        If there are missing positions data in a block then the missing days
        positions and transactions data are fetched from the API and written to
        the cache.

        """
        # BUG: Will fail on last block if today is in the block
        raise NotImplementedError("This method is not yet properly implemented.")


        from_date, to_date = check_dates(from_date, to_date)

        # We need the latest basics data
        models, instruments, investors = self.client.get_basics_data()

        generator = self.iter_read_time_series(from_date, to_date)
        for year, week, positions, transactions in generator:
            # Check that there are seven days in the week block
            dates_list = positions.date.drop_duplicates().to_list()
            if len(dates_list) == 7:
                logger.info(f"Block {year}-{week} has all days.")
                continue

            # Has missing days
            logger.warning(f"Block {year}-{week} has {7-len(dates_list)} missing days.")
            # Compute the dates in the week block
            start_date = pd.to_datetime(f"{year}-W{week}-1", format="%G-W%V-%u")
            iso_dates = pd.date_range(start_date, periods=7, freq="D")
            # Compute the dates missing in the week block
            missing_dates = [date for date in iso_dates if date not in dates_list]

            # For each date fetch api data and merge it with the existing data
            positions_list = list()
            transactions_list = list()
            for date in missing_dates:
                date = date.date()  # From pd.Timestamp to datetime.date
                logger.info(f"Fetching data for missing date {date}.")
                positions_api, transactions_api = self.client.get_time_series(date, date)
                assert transactions_api.price.dtype == float, "Expected a float price."
                positions_list.append(positions_api)
                transactions_list.append(transactions_api)
            # Concatenate the missing data
            positions_api = PositionsFrame.concat(positions_list)
            transactions_api = TransactionsFrame.concat(transactions_list)
            assert transactions_api.price.dtype == float, "Expected a float price."

            # Merge models, instruments, investors data to positions and
            # transactions.
            positions_api.merge(models, instruments, investors)
            transactions_api.merge(models, instruments, investors)
            assert transactions_api.price.dtype == float, "Expected a float price."
            # Lastly merge basics-data.
            models.merge(instruments)
            investors.merge(models)

            # Construct Data objects and do not verify as we know data is missing
            data_api = Data(
                models.data, instruments.data, investors.data,
                positions_api.data, transactions_api.data,
                verify_integrity=False)
            assert data_api.transactions.price.dtype == float, "Expected a float price."
            # Write back to cache and do not update last date
            self.write_cache(data_api)

    def get_iso_periods(self, from_date, to_date, reverse=False):
        """Get the ISO week periods in a date range.

        Parameters
        ----------
        from_date : datetime.date, optional
            Inclusive start date of the time-series part of the returned data.
        to_date : datetime.date, optional
            Inclusive last date of the time-series part of the returned data.
        reverse : bool, optional
            If `False` then iterate in reverse `date` rank.

        Returns
        -------
        pandas.DataFame
            The dataframe's index is a pandas.DatetimeIndex. The dataframe has
            columns `year` and `week` corresponding to the ISO week numbers that
            are fully or partly contained the specified date range. The rows are
            unique.
        """
        from_date, to_date = check_dates(from_date, to_date)

        # Generate a list of dates between from_date and to_date and from that
        # an ISO calendar list of year & week number and then drop the week day.
        iso_periods = (
            pd.date_range(from_date, to_date, freq="D")
            .isocalendar()
            .drop(columns="day")
            .drop_duplicates()
        )
        iso_periods = iso_periods.sort_index(ascending=not reverse)

        return iso_periods

    def get_num_blocks(self, from_date=None, to_date=None):
        """Return the expected ISO weekly data blocks in date range.

        This is useful for progress measurement, for example when using
        ``tqdm`` as a progress bar, it needs the expected number of blocks.

        Parameters
        ----------
        from_date : datetime.date, optional
            Inclusive start date of the time-series part of the returned data.
        to_date : datetime.date, optional
            Inclusive last date of the time-series part of the returned data.

        Note
        ----
        The `to_date` and `from_date` parameters should be the same as those in
        the intended subsequent use of the ``iter_read_cache`` method.

        Returns
        -------
        pandas.DataFame
            The dataframe's index is a pandas.DatetimeIndex. The dataframe has
            columns `year` and `week` corresponding to the ISO week numbers that
            are fully or partly contained the specified date range. The rows are
            unique.
        """
        from_date, to_date = check_dates(from_date, to_date)
        iso_periods = self.get_iso_periods(from_date, to_date)

        return iso_periods

    def read_basics_data(self):
        """Read the basics data from the cache.

        Returns
        -------
        tuple
            The tuple contains the pandas.DataFrames of the models, instruments
            and investors data.
        """
        _path = self._path
        filename = f"{self.BASICS_DATA_FILE}.pkl"
        path = os.path.join(_path, filename)
        # if not exists
        if os.path.exists(path):
            file = open(path, "rb")
            try:
                data = pickle.load(file)
            except Exception as ex:
                logger.exception(f"Exception reading basics data file {filename}.")
                raise ex
            else:
                models, instruments, investors = data
                logger.debug(f"Success reading basics data file {filename}.")
            finally:
                file.close()
        else:
            logger.debug(f"Not found reading basics data file {filename}.")

        # Add the missing proxy_isin column to the instruments data using the
        # InstrumentsFrame constructor
        instruments = InstrumentsFrame(instruments).data

        return models, instruments, investors

    def iter_read_time_series(self, from_date=None, to_date=None):
        """Iterator over the cache time-series components in ISO weekly blocks.

        Note
        ----
        Reads cache time-series block files for every block that has any dates
        that are spanned by the inclusive [from_date, to_date] range.

        Parameters
        ----------
        from_date : datetime.date, optional
            Inclusive start date of the time-series part of the returned data.
        to_date : datetime.date, optional
            Inclusive last date of the time-series part of the returned data.

        Yields
        ------
        tuple
            The tuple contains the year, week, positions and transactions data.
            The positions and transactions data are pandas.DataFrames.

        See also
        --------
        Data
        """
        from_date, to_date = check_dates(from_date, to_date)

        # Read cache files for every block that has any dates that are spanned
        # by the inclusive [from_date, to_date] range noting that some blocks
        # may not yet exist in the cache.
        iso_periods = self.get_iso_periods(from_date, to_date)
        for _, row in iso_periods.iterrows():
            year = row.year
            week = row.week
            filename = self.get_week_block_path(year, week)
            path = os.path.join(self._path, filename)
            # Read the time-series block file if it exists, if not then just log it.
            if os.path.exists(path):
                with open(path, "rb") as file:
                    # There was an issue with using pickle.load after pandas
                    # upgrade to > 2.0.0
                    positions, transactions = pd.read_pickle(file)
                    assert transactions.price.dtype == float, "Expected a float price."
                logger.debug(f"Success reading time-series file {filename}.")
                yield year, week, positions, transactions
            else:
                logger.debug(f"File not found reading time-series file {filename}.")


    def write_cache(self, new: Data):
        """Write API data to the year/week specific cache files.

        Any existing time-series rows in the cache will be updated with the
        time-series rows in the `new` argument. All time-series rows in the
        `new` argument which are not in the cache will be added. Dataframe rows
        are uniquely identified by their `date` column.

        The basics-data `models`, `instruments` and `investors` of each weekly
        cache data block of the original cache data are kept and written back.
        However the time-series data `positions` and `transactions` are
        updated with the data from the `new` argument.

        This method will not update the `last date cache file` as the data
        written here may not represent the full data date range. Instead make
        use of the ``write_last_cache_date`` method to control the update of the
        `last date cache file`.

        Parameters
        ----------
        new : Data
            Data to be written to cache in year/week specific cache block files.
        """
        # Read the cache data in the new data range, and if any data exists then
        # update the cache data with the new data before writing the data back
        # to the cache. This prevents cache data loss! Do not slice away data
        # outside of the date range as this will cause data to be lost in the
        # cache write-back below.
        assert new.transactions.price.dtype == float, "Expected a float price."
        from_date, to_date = new.date_range()
        cache_data = self.read_cache(
            from_date, to_date,
            # Use the newest basics data instead of the old cache basics data.
            models=new.models, instruments=new.instruments, investors=new.investors,
            slice=False, progress_bar=False
        )
        if cache_data is not None:
            assert cache_data.transactions.price.dtype == float, "Expected a float price."
            # Update existing cache data with the new data. Note that this
            # should be verified data in the update.
            updated = cache_data.update(new)
            assert updated.transactions.price.dtype == float, "Expected a float price."
        else:
            # No cache data for this date range so use the new data as is
            updated = new

        # TODO: Make the pickle dumps below atomic by writing to a temporary file and
        # then renaming it to the final file name upon success of all writes.

        # Iteratively write-back the data as ISO-week-long time-series data
        # blocks.
        for year, week, data_item in updated.iter_periods():
            assert data_item.transactions.price.dtype == float, "Expected a float price."
            time_series = data_item.positions, data_item.transactions
            path = self.get_week_block_path(year, week)
            with open(path, "wb") as file:
                pickle.dump(time_series, file, protocol=self.PICKLE_PROTOCOL)
                logger.debug(f"Success writing time-series file {path}.")

        # Write basics data to cache only after a successful time-series write
        basics_data = new.models, new.instruments, new.investors
        filename = f"{self.BASICS_DATA_FILE}.pkl"
        path = os.path.join(self._path, filename)
        with open(path, "wb") as file:
            pickle.dump(basics_data, file, protocol=self.PICKLE_PROTOCOL)
            logger.debug(f"Success writing basics data file {filename}.")

    def write_last_date(self, last_date: datetime.date):
        """Write the last date to the cache.

        Parameters
        ----------
        last_date : datetime.date
            The last date of the positions component of the time-series data.
        """
        filename = f"{self.LAST_DATE_FILE}.pkl"
        path = os.path.join(self._path, filename)
        with open(path, "wb") as stream:
            pickle.dump(last_date, stream, protocol=self.PICKLE_PROTOCOL)

    def get_week_block_path(self, year, week):
        """Return the path to the cache week block file.

        Parameters
        ----------
        year : int
            The ISO year number of the week block.
        week : int
            The ISO week number of the week block.

        Return
        ------
        str
            The path to the cache week block file.
        """
        filename = f"{self.TIME_SERIES_FILE}-{year}-{week}.pkl"
        path = os.path.join(self._path, filename)
        return path


class FundProvider:
    """Provide Finworks portfolio records as ``funds.Fund`` objects.

    Parameters
    ----------
    asset_base : asset.Manager()
        The asset base that is used to resolve the ISINs of the fund
        holdings. This contains the database session that must be closed
        when no longer needed.
    last_date : datetime.date, optional
       The last date to be used to get the latest data. If not set then the
       last date in the cache is used.
    test_cache : bool
        If set to `True` then test if the cache is fresh and if not then
        raise a ``CacheError``, else ignore the test.
    """

    def __init__(self, asset_base: Manager, last_date: datetime.date = None) -> None:
        """Initialisation."""
        cache = Cache()
        if not cache.is_up_to_date(last_date):
            date = cache.last_date()
            raise CacheError(
                f"Cache is not up-to-date. It`s Last date is {date}. "
                "Please update it now."
            )
        self.asset_base = asset_base

        # Get and keep cache data for the last date. If last date is not
        # provided then use the cache last-date.
        if last_date is None:
            last_date = cache.last_date()
        self.data = cache.get_last_data(last_date)

        # Test that all ISINs are available in the asset_base
        err_list = self.test_missing_isins(self.data)
        if len(err_list) != 0:
            raise Exception(f"Missing ISINs in `asset_base`: {err_list}.")

        self.cache = cache
        self.last_date = last_date

    def __repr__(self):
        """Return the official string output."""
        txt = (
            f"{self.__class__.__name__}"
            f"(asset_base={self.asset_base!r}, "
            f"last_date={self.last_date}, "
            f"test_cache={self.test_cache})"
        )
        return txt

    def get_funds_list(self, uuid_list: list = None, model_ticker_list: list = None) -> FundsList:
        """Get the latest fund list.

        Parameters
        ----------
        uuid_list : list, optional
            A list of uuids to be used to filter the funds. If not set then all
            the funds are returned.
        model_ticker_list : list, optional
            A list of model tickers to be used to filter the funds. If not set
            then all the funds are returned.

        If any filters are set then the fund positions as well as the models and
        investors are filtered.

        Returns
        -------
        funds.FundList
            A list of funds based on the latest available data.
        """
        models_df = self.get_models_dataframe()
        investors_df = self.get_investor_dataframe()
        positions_df = self.get_positions_dataframe()
        # Filter fund positions by UUID.
        if uuid_list:
            positions_df = positions_df[positions_df.client_account_id.isin(uuid_list)]
        # Filter fund positions by model ticker.
        if model_ticker_list:
            positions_df = positions_df[
                positions_df.model_ticker.isin(model_ticker_list)
            ]

        # If any fund positions filters apply then filter other dataframes too.
        if uuid_list or model_ticker_list:
            models_df = models_df[
                models_df.ticker.isin(positions_df.model_ticker.unique())
            ]
            investors_df = investors_df[
                investors_df.client_account_id.isin(positions_df.client_account_id.unique())
            ]

        return FundsList.from_data(self.last_date, positions_df, models_df, investors_df)

    def get_models_dataframe(self) -> DataFrame:
        """Get latest models dataframe from the cached data.

        Returns
        -------
        pandas.DataFrame

        Return
        ------
        pandas.DataFrame
            A dataframe containing the model security weights data.
            Columns:
                ticker : str
                    The model's ticker.
                name : str
                    The models's long name.
                security : asset_base.asset.Listed
                    A model's security
                weight : float
                    The weight of the security. Sum(weights) = 1.0.

        """
        models = self.data.models

        # Fix data types
        models.value = models.value.astype(float)
        # Create a dict of securities with the unique ISINs as the keys
        map_dict = dict()
        column = models["isin"].drop_duplicates()
        # Get the ISIN-securities dictionary mapping
        session = self.asset_base.session
        for _, isin in column.items():
            map_dict[isin] = Listed.factory(session, isin=isin)
        # From ISIN column create securities column
        models["security"] = models["isin"].replace(to_replace=map_dict)
        # Drop columns
        models = models.drop(columns=["isin", "ticker", "status"])
        # Rename columns
        models = models.rename(columns={"model_ticker": "ticker", "value": "weight"})
        # Adjust weights from a percentage to a number
        models.weight /= 100.0
        # Reset the index
        models = models.reset_index(drop=True)
        # Keep only required columns
        models = models[["ticker", "name", "security", "weight"]]


        return models

    def get_investor_dataframe(self) -> DataFrame:
        """Get the fund investor data.

        Returns
        -------
        pandas.DataFrame
            A dataframe with investor data related to each dun by `UUID`.
            Columns:
                contract_number : str
                    A unique fund identifier.
                contract_id : str
                    A platform specific unique client identifier.
                name : str
                    A string containing the client's given names.
        """
        investors = self.data.investors[
            ["client_account_id", "id_number", "name", "take_on_date"]
        ].drop_duplicates()

        return investors

    def get_positions_dataframe(self) -> DataFrame:
        """Get latest funds positions dataframe from the cached data.

        Returns
        -------
        pandas.DataFrame
            A dataframe with the funds positions (units, cash account &
            settlement account). Columns:
                model_ticker : str
                    The model's ticker.
                client_account_id : str
                    A unique fund identifier
                security : asset.Listed, funds.CashAccount
                        or funds.SettlementAccount
                    An instance of a security holding.
                units : float
                    The number of units of the above security held.
        """
        positions = self.data.positions
        # Translate the positions DataFrame format adding a securities column
        cash = self._translate_cash_positions(positions)
        settlement = self._translate_settlement_positions(positions)
        units = self._translate_security_positions(positions)
        # The above three DataFrames, cash, settlement & units, have their
        # `security` column filled with the proper security instances,
        # `funds.CashAccount`, `funds.SettlementAccount` & `asset.Listed`
        # respectively. Now we may concatenate them without causing confusion.
        positions = pd.concat([cash, settlement, units], axis="index")
        # Keep only required columns
        positions = positions[["model_ticker", "client_account_id", "security", "units"]]

        return positions

    def _translate_settlement_positions(self, positions: DataFrame) -> DataFrame:
        """For settlement account cash positions.

        Add security column and rename or drop columns."""
        session = self.asset_base.session
        # Cash settlement account positions selector
        settle = positions[
            (positions.type == "Money") & (positions.ticker.str.endswith("-S"))
        ]
        # Get cash ticker to cash security mapping
        column = settle.ticker.drop_duplicates()
        map_dict = dict()
        for _, ticker in column.items():
            map_dict[ticker] = SettlementAccount.factory(
                session, ticker=ticker.rstrip("-S")
            )
        # From ticker column create securities column
        settle = settle.copy()
        settle["security"] = settle["ticker"].replace(to_replace=map_dict)
        # Drop columns
        settle = settle.drop(
            columns=[
                "date",
                "price_date",
                "type",
                "value",
                "currency",
                "isin",
                "ticker",
                "status",
            ]
        )

        return settle

    def _translate_cash_positions(self, positions: DataFrame) -> DataFrame:
        """For portfolio cash transactions (non-settlement).

        Add security column and rename or drop columns."""
        session = self.asset_base.session
        # Cash position selector, not settlement account
        cash = positions[
            (positions.type == "Money") & (~positions.ticker.str.endswith("-S"))
        ]
        # Get cash ticker to cash security mapping
        column = cash.ticker.drop_duplicates()
        map_dict = dict()
        for _, ticker in column.items():
            map_dict[ticker] = CashAccount.factory(session, ticker=ticker)
        # From ticker column create securities column
        cash = cash.copy()
        cash["security"] = cash["ticker"].replace(to_replace=map_dict)
        # Drop columns
        cash = cash.drop(
            columns=[
                "date",
                "price_date",
                "type",
                "value",
                "currency",
                "isin",
                "ticker",
                "status",
            ]
        )

        return cash

    def _translate_security_positions(self, positions: DataFrame) -> DataFrame:
        """For portfolio security positions.

        Add security column and rename or drop columns."""
        session = self.asset_base.session
        # Security position selector
        select = positions.type == "Unit"
        positions = positions[select]
        # Drop rows with zero units. This is a fix for Finworks data where some
        # weird looking securities show up with ISINs XS2323180583 and
        # XS2323180666
        positions = positions[positions.units != 0]
        # Get security ticker to security mapping
        column = positions["isin"].drop_duplicates()
        map_dict = dict()
        for _, isin in column.items():
            map_dict[isin] = Listed.factory(session, isin=isin)
        # From ticker column create securities column
        positions["security"] = positions["isin"].replace(to_replace=map_dict)
        # Drop columns
        positions = positions.drop(
            columns=[
                "date",
                "price_date",
                "type",
                "value",
                "currency",
                "isin",
                "ticker",
                "status",
            ]
        )

        return positions

    def test_missing_isins(self, data: Data) -> list:
        """Test that all ISINs in the data are present in ``asset_base``."""
        session = self.asset_base.session
        errata_list = list()

        # Test positions security isins
        select = data.positions.type == "Unit"
        positions = data.positions[select]
        column = positions["isin"].drop_duplicates()
        for _, isin in column.items():
            try:
                Listed.factory(session, isin=isin)
            except FactoryError:
                errata_list.append(isin)

        # Test positions security isins
        models = data.models
        column = models["isin"].drop_duplicates()
        for _, isin in column.items():
            try:
                Listed.factory(session, isin=isin)
            except FactoryError:
                errata_list.append(isin)

        return list(set(errata_list))

    def test_missing_tickers(self, data: Data) -> list:
        """Test that all tickers in the data are present in ``asset_base``."""
        session = self.asset_base.session
        errata_list = list()

        # Test positions security tickers
        select = data.positions.type == "Unit"
        positions = data.positions[select]
        column = positions["ticker"].drop_duplicates()
        for _, ticker in column.items():
            try:
                Listed.factory(session, ticker=ticker)
            except FactoryError:
                errata_list.append(ticker)

        # Test models security tickers
        models = data.models
        column = models["ticker"].drop_duplicates()
        for _, ticker in column.items():
            try:
                Listed.factory(session, ticker=ticker)
            except FactoryError:
                errata_list.append(ticker)

        return list(set(errata_list))


class TransactionsProvider:
    """Provide Finworks transactions in a standard for the history module
    """