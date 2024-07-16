#!/usr/bin/env unittest
# -*- coding: utf-8 -*-
# <nbformat>3.0</nbformat>

"""Test suite for the finworks module.

Copyright (C) 2015 Justin Solms <justinsolms@gmail.com>.
This file is part of the fundmanage module.
The fundmanage module can not be modified, copied and/or
distributed without the express permission of Justin Solms.

"""

import datetime
import ssl
import unittest
from aiohttp import web
import aiohttp
import asyncio
import threading
import time
import logging
import ipdb

# Import the mock server
from fundmanage3 import get_data_path
from fundmanage3.finworks_mock_server import create_server

# Classes to be tested
from fundmanage3.finworks import APIClient, Cache, ClientInterface, Data, FinworksAPIError
from fundmanage3.finworks import ModelsTask, InstrumentsTask, InvestorsTask
from fundmanage3.finworks import PositionsTask, TransactionsTask
from fundmanage3.finworks import ModelsFrame, InstrumentsFrame, InvestorsFrame
from fundmanage3.finworks import PositionsFrame, TransactionsFrame
from fundmanage3.finworks import FundProvider
from fundmanage3.finworks import START_DATE

from asset_base.manager import Manager
from fundmanage3.funds import FundsList


# Get module-named logger.
logger = logging.getLogger(__name__)


# import warnings
# warnings.filterwarnings(
#     action="ignore", message="unclosed", category=ResourceWarning)

# Set up test date
TEST_DATE = datetime.date(2021, 8, 1)
# TEST_DATE = MAIN_TEST_DATE

# Use test data fixtures instead of the actual API data
USE_TEST_SERVER = True
TEST_URL = "http://localhost:8080"


class TestAuthentication(unittest.TestCase):
    """Test suite for the Finworks certificates and keys."""

    @classmethod
    def setUpClass(cls) -> None:
        """Set up test class."""
        cls.cert_path = get_data_path("finworks/certificates/secure.aospartner.com/cert.crt")
        cls.key_path = get_data_path("finworks/certificates/secure.aospartner.com/cert.key")
        cls.token = "QyT7oTnIvmiq5swQ"
        cls.url = "https://secure.aospartner.com/api/modelmanager/model-portfolios"

    def setUp(self) -> None:
        """Set up test method."""
        pass

    def test_authentication(self):
        """Test the Finworks certificates and keys."""
        async def fetch(url, cert_path, key_path, token):
            # Create SSL context and load cert and key
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(certfile=cert_path, keyfile=key_path)

            headers = {
                "Authorization: Bearer": token,
                "Content-Type": "application/json"
            }

            try:
                async with aiohttp.ClientSession() as session:
                    try:
                        async with session.get(url, headers=headers, ssl=ssl_context) as response:
                            try:
                                json_records = await response.json()
                                return json_records
                            except aiohttp.ContentTypeError as ex:
                                # We got a response but it was not JSON
                                text = await response.text()
                                # Set the exception as the response
                                raise FinworksAPIError(
                                    f"{ex.message}, url={ex.request_info.url}\n"
                                    f"Text received was:\n"
                                    f"{text}")
                            except Exception as e:
                                print(f"Error reading response text: {e}")
                    except ssl.SSLCertVerificationError as e:
                        print(f"SSL certificate verification error occurred: {e}")
                    except aiohttp.ClientConnectorCertificateError as e:
                        print(f"Client connector certificate error occurred: {e}")
                    except ssl.SSLError as e:
                        print(f"SSL error occurred: {e}")
                    except aiohttp.ClientError as e:
                        print(f"Client error occurred: {e}")
                    except Exception as e:
                        print(f"An unexpected error occurred during the request: {e}")
            except aiohttp.ClientError as e:
                print(f"Client session error occurred: {e}")
            except Exception as e:
                print(f"An unexpected error occurred during session creation: {e}")

        async def main():
            content = await fetch(self.url, self.cert_path, self.key_path, self.token)
            if content:
                self.assertEqual(content['size'], len(content['data']))
                item = content['data'][0]
                # Test dict keys
                self.assertTrue('Model portfolio id' in item)
                self.assertTrue('Splits' in item)
                # We can add more dict key tests here for greater certainty

        # Commented out to prevent execution in this environment
        asyncio.run(main())


class TestServer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(level=logging.DEBUG)
        cls.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(cls.loop)
        cls.app = create_server()
        cls.runner = web.AppRunner(cls.app)
        cls.loop.run_until_complete(cls.runner.setup())
        cls.site = web.TCPSite(cls.runner, 'localhost', 8080)
        cls.loop.run_until_complete(cls.site.start())

        cls.server_thread = threading.Thread(target=cls.loop.run_forever)
        cls.server_thread.start()
        time.sleep(1)  # Give the server some time to start

    @classmethod
    def tearDownClass(cls):
        cls.loop.call_soon_threadsafe(cls.loop.stop)
        cls.server_thread.join()
        cls.loop.run_until_complete(cls.runner.cleanup())

    def test_example(self):
        # Example test
        async def fetch():
            async with aiohttp.ClientSession() as session:
                async with session.get('http://localhost:8080/api/modelmanager/model-portfolios') as resp:
                    self.assertEqual(resp.status, 200)
                    data = await resp.json()
                    # Assert the data structure
                    self.assertIsInstance(data, dict)
                    self.assertIn('data', data)
                    self.assertIn('size', data)
                    self.assertEqual(len(data['data']), data['size'])
                    self.assertIsInstance(data['data'], list)
                    self.assertIsInstance(data['data'][0], dict)

        asyncio.run(fetch())


class TestAPIClient(unittest.TestCase):
    """Test suite for the ModelsTask class."""

    @classmethod
    def setUpClass(cls) -> None:
        """Set up test class."""
        # Start server
        TestServer.setUpClass()

    def setUp(self) -> None:
        """Set up test method."""
        if USE_TEST_SERVER:
            self.api_client = APIClient(test_url=TEST_URL)
        else:
            self.api_client = APIClient()

    @classmethod
    def tearDownClass(cls) -> None:
        # Stop server
        TestServer.tearDownClass()

    def test_single(self):
        """Test the API class."""
        self.assertIsInstance(self.api_client, APIClient)
        # Add fetch tasks
        self.api_client.add_task(ModelsTask)
        # Fetch tasks instead of responses
        tasks_list = self.api_client.fetch(return_tasks=True)
        # Check results
        self.assertIsInstance(tasks_list, list)
        self.assertEqual(len(tasks_list), 1)
        # Check tasks responses attributes are not exceptions
        self.assertNotIsInstance(tasks_list[0].response, Exception)
        # Check tasks are the expected task types
        self.assertIsInstance(tasks_list[0], ModelsTask)
        # Check tasks responses are the expected response types
        self.assertIsInstance(tasks_list[0].response, ModelsFrame)

    def test_api(self):
        """Test the API class."""
        self.assertIsInstance(self.api_client, APIClient)
        # Add fetch tasks
        self.api_client.add_task(ModelsTask)
        self.api_client.add_task(InstrumentsTask)
        self.api_client.add_task(InvestorsTask)
        self.api_client.add_task(PositionsTask, date=TEST_DATE)
        self.api_client.add_task(TransactionsTask, date=TEST_DATE)
        # Fetch tasks instead of responses
        tasks_list = self.api_client.fetch(return_tasks=True)
        # Check results
        self.assertIsInstance(tasks_list, list)
        self.assertEqual(len(tasks_list), 5)
        # Check tasks responses attributes are not exceptions
        self.assertNotIsInstance(tasks_list[0].response, Exception)
        self.assertNotIsInstance(tasks_list[1].response, Exception)
        self.assertNotIsInstance(tasks_list[2].response, Exception)
        self.assertNotIsInstance(tasks_list[3].response, Exception)
        self.assertNotIsInstance(tasks_list[4].response, Exception)
        # Check tasks are the expected task types
        self.assertIsInstance(tasks_list[0], ModelsTask)
        self.assertIsInstance(tasks_list[1], InstrumentsTask)
        self.assertIsInstance(tasks_list[2], InvestorsTask)
        self.assertIsInstance(tasks_list[3], PositionsTask)
        self.assertIsInstance(tasks_list[4], TransactionsTask)
        # Check tasks responses are the expected response types
        self.assertIsInstance(tasks_list[0].response, ModelsFrame)
        self.assertIsInstance(tasks_list[1].response, InstrumentsFrame)
        self.assertIsInstance(tasks_list[2].response, InvestorsFrame)
        self.assertIsInstance(tasks_list[3].response, PositionsFrame)
        self.assertIsInstance(tasks_list[4].response, TransactionsFrame)

class TestClientInterface(unittest.TestCase):
    """Test suite for the ClientInterface class."""

    @classmethod
    def setUpClass(cls) -> None:
        """Set up test class."""
        TestServer.setUpClass()

    def setUp(self) -> None:
        """Set up test method."""
        if USE_TEST_SERVER:
            self.client = ClientInterface(test_url=TEST_URL)
        else:
            self.client = ClientInterface()

    @classmethod
    def tearDownClass(cls) -> None:
        """Tear down test class."""
        TestServer.tearDownClass()

    def test_get_models(self):
        """Test the ClientInterface.get_models method."""
        self.assertIsInstance(self.client, ClientInterface)
        # Test the get_models method
        models = self.client.get_models()
        self.assertIsInstance(models, ModelsFrame)

    def test_get_instruments(self):
        """Test the ClientInterface.get_instruments method."""
        # Test the get_instruments method
        instruments = self.client.get_instruments()
        self.assertIsInstance(instruments, InstrumentsFrame)

    def test_get_investors(self):
        """Test the ClientInterface.get_investors method."""
        # Test the get_investors method
        investors = self.client.get_investors()
        self.assertIsInstance(investors, InvestorsFrame)

    def test_get_positions(self):
        """Test the ClientInterface.get_positions method."""
        # Test the get_positions method
        positions = self.client.get_positions(date=TEST_DATE)
        self.assertIsInstance(positions, PositionsFrame)

    def test_get_transactions(self):
        """Test the ClientInterface.get_transactions method."""
        # Test the get_transactions method
        transactions = self.client.get_transactions(date=TEST_DATE)
        self.assertIsInstance(transactions, TransactionsFrame)

    def test_get_basics_data(self):
        """Test the ClientInterface.get_basics_data method."""
        # Test the get_basics_data method
        basics_data = self.client.get_basics_data()
        models, instruments, investors = basics_data
        self.assertIsInstance(models, ModelsFrame)
        self.assertIsInstance(instruments, InstrumentsFrame)
        self.assertIsInstance(investors, InvestorsFrame)

    def get_get_time_series_data(self):
        """Test the ClientInterface.get_time_series method."""
        # Test the get_time_series method
        time_series_data = self.client.get_time_series(date=TEST_DATE)
        positions, transactions = time_series_data
        self.assertIsInstance(positions, PositionsFrame)
        self.assertIsInstance(transactions, TransactionsFrame)

    def test_get_data(self):
        """Test the ClientInterface.get_data method."""
        # Test the get_data method
        data = self.client.get_data(date=TEST_DATE)
        self.assertIsInstance(data, Data)

class TestCache(unittest.TestCase):
    """Test suite for the Cache class.

    Warning
    -------
    This test suite will delete the cache if it exists. Use with caution.
    """

    # Compare tis to CACHE_PATH in finworks.py
    ALT_CACHE_PATH = get_data_path("finworks/unittest_cache")

    @classmethod
    def setUpClass(cls) -> None:
        """Set up test class."""
        TestServer.setUpClass()

    def setUp(self) -> None:
        """Set up test method."""
        if USE_TEST_SERVER:
            self.cache = Cache(alt_path=self.ALT_CACHE_PATH, test_url=TEST_URL)
        else:
            self.cache = Cache()
        # Delete the cache
        self.cache._delete()  # NOTE: Use with caution - back up the cache first

    @classmethod
    def tearDownClass(cls) -> None:
        """Tear down test class."""
        TestServer.tearDownClass()

    def test_cache_increment(self):
        """Test the Cache class increment option."""
        # Update the cache over 10 days form start date
        self.cache.update(increment=1)
        self.cache.update(increment=2)
        self.cache.update(increment=3)
        self.cache.update(increment=4)
        # Read the cache form start date to end date
        data_cache = self.cache.get_cache_data(from_date=START_DATE, to_date=self.cache.last_date())
        data_api = self.cache.get_api_data(from_date=START_DATE, to_date=self.cache.last_date())
        Data.assert_equal(data_cache, data_api)
        assert data_cache.transactions.price.dtype == float, 'Expected float data type'
        assert data_api.transactions.price.dtype == float, 'Expected float data type'

    def test_cache_increment_no_rollback(self):
        """Test the Cache class increment option with no roll back to test if
        there is data loss on cache write."""
        # Update the cache over 10 days form start date
        self.cache.update(increment=1, roll_back=0)
        self.cache.update(increment=2, roll_back=0)
        self.cache.update(increment=3, roll_back=0)
        self.cache.update(increment=4, roll_back=0)
        # Read the cache form start date to end date
        data_cache = self.cache.get_cache_data(from_date=START_DATE, to_date=self.cache.last_date())
        data_api = self.cache.get_api_data(from_date=START_DATE, to_date=self.cache.last_date())
        Data.assert_equal(data_cache, data_api)

    def test_cache_increment_and_rollback(self):
        """Test the Cache class increment option with no roll back to test if
        there is data loss on cache write."""
        # Update the cache over 10 days form start date
        self.cache.update(increment=1)
        self.cache.update(increment=4)
        self.cache.update(increment=4, roll_back=4)
        # Read the cache form start date to end date
        data_cache = self.cache.get_cache_data(from_date=START_DATE, to_date=self.cache.last_date())
        data_api = self.cache.get_api_data(from_date=START_DATE, to_date=self.cache.last_date())
        Data.assert_equal(data_cache, data_api)

    def test_cache_batch(self):
        """Test the Cache class batch update option."""
        self.cache.batch_update(batch_size=5, batches=2)
        # Read the cache form start date to end date
        data_cache = self.cache.get_cache_data(from_date=START_DATE, to_date=self.cache.last_date())
        data_api = self.cache.get_api_data(from_date=START_DATE, to_date=self.cache.last_date())
        Data.assert_equal(data_cache, data_api)

@unittest.skip("Skip test as the repair methods are not yet fully implemented.")
class TestCacheRepair(unittest.TestCase):
    """Test suite for the Cache class.

    Note
    ----
    This can only be used on a production cache that has files with missing
    positions and transactions dates. These block file set for 2023-W17 and
    2023-W18 can be found in the `tests/fixtures/finworks_bad_block_set`
    directory. They must be copied to the cache directory to test the repair.

    (base) justin@sundesk:~$ ncal -W7 -bwM 4 2023
        April 2023
     w| Mo Tu We Th Fr Sa Su
    13|                 1  2
    14|  3  4  5  6  7  8  9
    15| 10 11 12 13 14 15 16
    16| 17 18 19 20 21 22 23
    17| 24 25 26 27 28 29 30

    (base) justin@sundesk:~$ ncal -W7 -bwM 5 2023
            May 2023
     w| Mo Tu We Th Fr Sa Su
    18|  1  2  3  4  5  6  7
    19|  8  9 10 11 12 13 14
    20| 15 16 17 18 19 20 21
    21| 22 23 24 25 26 27 28
    22| 29 30 31

    """

    # Compare tis to CACHE_PATH in finworks.py
    ALT_CACHE_PATH = get_data_path("finworks/unittest_cache")

    @classmethod
    def setUpClass(cls) -> None:
        """Set up test class."""
        TestServer.setUpClass()

    def setUp(self) -> None:
        """Set up test method."""
        if USE_TEST_SERVER:
            self.cache = Cache(alt_path=self.ALT_CACHE_PATH, test_url=TEST_URL)
        else:
            self.cache = Cache()

    @classmethod
    def tearDownClass(cls) -> None:
        """Tear down test class."""
        TestServer.tearDownClass()

    def test_cache_repair(self):
        """Test the Cache class increment option."""
        start_date = datetime.date(2023, 4, 24)
        end_date = datetime.date(2023, 5, 7)
        self.cache.repair(start_date, end_date)
        data_cache = self.cache.get_cache_data(from_date=start_date, to_date=end_date)
        data_api = self.cache.get_api_data(from_date=start_date, to_date=end_date)
        Data.assert_equal(data_cache, data_api)


@unittest.skip("Tests not yet fully implemented.")
class TestFundProvider(unittest.TestCase):
    """Test suite for the FundProvider class."""

    @classmethod
    def setUpClass(cls) -> None:
        """Set up test class."""
        cls.asset_base = Manager()

    def setUp(self) -> None:
        """Set up test method."""
        self.today = datetime.date(2024, 4, 30)
        self.provider = FundProvider(self.asset_base, last_date=self.today)

    @classmethod
    def tearDownClass(cls) -> None:
        """Tear down test class."""
        cls.asset_base.close()

    def test___init__(self):
        """Test the FundProvider class."""
        self.assertIsInstance(self.provider, FundProvider)

    def test_get_funds_list(self):
        """Test the FundProvider.get_funds_list method."""
        model_ticker_list = ["IDXDISGROA"]
        funds_list = self.provider.get_funds_list(model_ticker_list=model_ticker_list)
        self.assertIsInstance(funds_list, FundsList)


class Suite(object):
    """Test suite"""

    def __init__(self):
        """Initialization."""
        suite = unittest.TestSuite()

        test_classes = [
            TestServer,
            TestAPIClient,
            TestClientInterface,
            TestCache,
        ]

        suites_list = list()
        loader = unittest.TestLoader()
        for test_class in test_classes:
            suites_list.append(loader.loadTestsFromTestCase(test_class))

        suite.addTests(suites_list)

        self.suite = suite

    def run(self):
        runner = unittest.TextTestRunner()
        runner.run(self.suite)


if __name__ == "__main__":
    suite = Suite()
    suite.run()
