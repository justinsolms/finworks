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
import unittest
from aiohttp import web
import aiohttp
import asyncio
import threading
import time
import logging

# Import the mock server
from fundmanage3.finworks_mock_server import create_server

# Classes to be tested
from fundmanage3.finworks import APIClient, Cache, ClientInterface, Data
from fundmanage3.finworks import ModelsTask, InstrumentsTask, InvestorsTask
from fundmanage3.finworks import PositionsTask, TransactionsTask
from fundmanage3.finworks import ModelsFrame, InstrumentsFrame, InvestorsFrame
from fundmanage3.finworks import PositionsFrame, TransactionsFrame


# Define test date ony in a single place
from fundmanage3.finworks import TEST_DATE as MAIN_TEST_DATE

# Get module-named logger.
logger = logging.getLogger(__name__)

# import warnings
# warnings.filterwarnings(
#     action="ignore", message="unclosed", category=ResourceWarning)

# Set up test date
TEST_DATE = datetime.datetime(2021, 8, 1)
# TEST_DATE = MAIN_TEST_DATE

# Use test data fixtures instead of the actual API data
USE_MOCK_SERVER = True
TEST_URL = "http://localhost:8080"


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
                    # Asset the data are a list of dict.
                    self.assertIsInstance(data, list)
                    self.assertIsInstance(data[0], dict)

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
        if USE_MOCK_SERVER:
            self.api_client = APIClient(TEST_URL)
        else:
            self.api_client = APIClient()

    @classmethod
    def tearDownClass(cls) -> None:
        # Stop server
        TestServer.tearDownClass()

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
        if USE_MOCK_SERVER:
            self.client = ClientInterface(TEST_URL)
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
    """Test suite for the Cache class."""

    @classmethod
    def setUpClass(cls) -> None:
        """Set up test class."""
        TestServer.setUpClass()

    def setUp(self) -> None:
        """Set up test method."""
        if USE_MOCK_SERVER:
            self.cache = Cache(test_url=TEST_URL)
        else:
            self.cache = Cache()
        # Delete the cache
        self.cache._delete()  # NOTE: Use with caution - back up the cache first

    @classmethod
    def tearDownClass(cls) -> None:
        """Tear down test class."""
        TestServer.tearDownClass()

    def test_cache(self):
        """Test the Cache class."""
        # Update the cache
        self.cache.update(increment=1)
        self.cache.update(increment=1)

class Suite(object):
    """Test suite"""

    def __init__(self):
        """Initialization."""
        suite = unittest.TestSuite()

        test_classes = [
            TestAPIClient,
            TestClientInterface,
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
