#!/usr/bin/env unittest
# -*- coding: utf-8 -*-
# <nbformat>3.0</nbformat>

"""Test suite for the financial_feed module.

Copyright (C) 2015 Justin Solms <justinsolms@gmail.com>.
This file is part of the fundmanage module.
The fundmanage module can not be modified, copied and/or
distributed without the express permission of Justin Solms.

"""
import asyncio
import datetime
import json
import logging
import aiohttp
import unittest
import aiounittest
import pandas as pd

from unittest.mock import patch, AsyncMock

# Classes to be tested
from fundmanage3.finworks import APIDirect, APISessionManager, Data
from fundmanage3.finworks import APIPaths
from fundmanage3.finworks import Cache

# Define test date ony in a single place
from fundmanage3.finworks import TEST_DATE

# Get module-named logger.
logger = logging.getLogger(__name__)

# import warnings
# warnings.filterwarnings(
#     action="ignore", message="unclosed", category=ResourceWarning)

def sync_runner(async_function):
    """A little cheat to run coroutines synchronously."""
    # Create a new event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Run the async function and wait for it to complete
    loop.run_until_complete(async_function())

    # Close the loop
    loop.close()

class TestSSLCertificates(aiounittest.AsyncTestCase):
    """Test suite for the SSL certificates.

    Does not use any of the finworks classes, except to get a test domain and
    path. Instead directly uses the aiohttp package to test the SSL
    certificates for the finworks API.
    """

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        # Use the _APIPaths class to set up fixtures and verify certificates
        api = APIPaths()
        # URL
        hostname = APIPaths.DOMAIN
        path = APIPaths.MODELS_PATH  # Need only one path for testing
        cls.url = f"https://{hostname}{path}"
        # SSL COntext
        cls.ssl_context = api._ssl_context

    @classmethod
    def tearDownClass(cls):
        """Tear down class test fixtures."""
        pass

    def setUp(self):
        """Set up test case fixtures."""
        pass

    def tearDown(self):
        """tear down test case fixtures."""
        pass

    def test_ssl(self):
        """Finworks SSL certificate validity testing"""

        async def task(session):
            async with session.get(self.url, ssl=self.ssl_context) as response:
                assert response.status == 200
                return await response.json()

        async def get_response():
            """Get function"""
            tasks_list = list()
            async with aiohttp.ClientSession() as session:
                tasks_list.append(task(session))
                response = await asyncio.gather(*tasks_list)
            return response

        response = asyncio.run(get_response())

        # Test response
        self.assertEqual([*response[0]], ["size", "data"])


class TestAPISessionManager(aiounittest.AsyncTestCase):
    """Test suite for the APISessionManager class."""

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        cls.models_path = APIPaths.MODELS_PATH
        cls.instruments_path = APIPaths.INSTRUMENTS_PATH
        cls.investors_path = APIPaths.INVESTORS_PATH
        cls.positions_path = APIPaths.POSITIONS_PATH
        cls.transactions_path = APIPaths.TRANSACTIONS_PATH
        cls.domain = APISessionManager().DOMAIN
        cls.models_url = f"https://{cls.domain}{cls.models_path}"
        cls.instruments_url = f"https://{cls.domain}{cls.instruments_path}"
        cls.investors_url = f"https://{cls.domain}{cls.investors_path}"
        cls.positions_url = f"https://{cls.domain}{cls.positions_path}?date={TEST_DATE}"
        cls.transactions_url = f"https://{cls.domain}{cls.transactions_path}?date={TEST_DATE}"
        # Test path and URL and params
        cls.test_path = cls.models_path
        cls.test_url = cls.models_url
        cls.params = {}
        # Read JSON response fixture as test data
        with open("tests/fixtures/models.json") as f:
            cls.json_response_fixture = json.load(f)

    @classmethod
    def tearDownClass(cls):
        """Tear down class test fixtures."""
        pass

    def setUp(self):
        """Set up test case fixtures."""
        pass

    def tearDown(self):
        """Tear down test case fixtures."""
        pass

    async def test___aenter__(self):
        """Test __aenter__ method."""
        async with self.api as api:
            self.assertIsInstance(api.session, aiohttp.ClientSession)
            self.assertIsInstance(api.conn, aiohttp.TCPConnector)

    async def test___aexit__(self):
        """Test __aexit__ method."""
        async with self.api as api:
            pass
        self.assertTrue(api.session.closed)
        self.assertTrue(api.conn.closed)

    async def run_then_assert(self, url, params, json_response_fixture=None):
        async with APISessionManager() as api:
            response = await api.get_response(url, params)
            self.assertIsInstance(response, list)
            self.assertTrue(len(response) > 0, "Response is empty.")
            self.assertTrue(all(isinstance(item, dict) for item in response))
            if json_response_fixture:
                # NOTE: The line below can only be used if the fixture is up to
                # date with the latest API models data. These models change
                # regularly. Use the fundmanage3.finworks.CollectJSONResponse
                # class to update the fixture files.
                self.assertEqual(response, json_response_fixture)

    async def test_get_response_actual(self):
        """Test get_response method with the actual API response."""
        # Use a test URL and params
        test_url = self.test_url
        test_params = self.params
        # Run then asser results
        await self.run_then_assert(test_url, test_params)

    @unittest.skip("Mocking the session manager is not working.")
    @patch("fundmanage3.finworks.APISessionManager", autospec=APISessionManager)
    async def test_get_response_mock(self, mock_session_manager):
        """Test get_response method with a mock API response."""
        # Use a test URL and params
        test_url = f"https://{APISessionManager.DOMAIN}{self.models_path}"
        test_params = self.params

        # Mock the response of the get request
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=self.json_response_fixture)

        # Mock the session manager
        async with mock_session_manager as api:
            response = await api.get_response(test_url, test_params)
            self.assertIsInstance(response, list)
            self.assertTrue(len(response) > 0, "Response is empty.")
            self.assertTrue(all(isinstance(item, dict) for item in response))
            # NOTE: The line below can only be used if the fixture is up to date
            # with the latest API models data. These models change regularly.
            # Use the fundmanage3.finworks.CollectJSONResponse class to update
            # the fixture files.
            # self.assertEqual(response, self.json_response_fixture)

    async def test_get_retries(self):
        """Test get_retries using a mock ``ClientSession.get`` response."""
        # Use a test path
        test_path = self.test_path

        async with self.api as api:
            response = await api.get_retries(test_path)
            self.assertIsInstance(response, list)
            self.assertTrue(len(response) > 0, "Response is empty.")
            self.assertTrue(all(isinstance(item, dict) for item in response))


class TestAPIPaths(aiounittest.AsyncTestCase):
    """Test suite for the APIPaths class.

    The test date is 2023-12-20.

    """

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        # Date on which there were transactions
        cls.test_date = TEST_DATE

    def setUp(self):
        """Set up test case fixtures."""
        # Use test data to save API hits and time
        self.use_test_data = True
        self.api_obj = APIPaths(use_test_data=self.use_test_data)

    async def test___init__(self):
        """Test Initialization."""
        # Is this a subclass of _API?
        async with self.api_obj as api:
            self.assertIsInstance(api, APIPaths)

    def test_runner(self):
        """Get multiple requests tasks in the runner."""

        # NOTE: the lack of assert statements in this test is intentional dur to the built in checks in the called methods.

        # Data Gathering awaitable
        async def get_results():
            async with self.api_obj as api:
                tasks_list = list()
                # Create all tasks
                tasks_list.append(api.get_models())
                tasks_list.append(api.get_instruments())
                tasks_list.append(api.get_investors())
                # Gether task to run
                results = await asyncio.gather(*tasks_list)
            return results

        # Run three tasks
        models, instruments, investors = asyncio.run(get_results())

    async def test_get_models(self):
        """List the available models on the system linked to the Model Manager."""
        async with self.api_obj as api:
            await api.get_models()

    async def test_get_instruments(self):
        """List the available instruments on the system."""
        async with self.api_obj as api:
            await api.get_instruments()

    async def test_get_investors(self):
        """List the available investors on the system."""
        async with self.api_obj as api:
            await api.get_investors()

    async def test_get_positions(self):
        """List the available positions on the system."""
        async with self.api_obj as api:
            await api.get_positions(date=self.test_date)

    async def test_get_transactions(self):
        """List the available transactions on the system."""
        async with self.api_obj as api:
            await api.get_transactions(date=self.test_date)


class TestData(unittest.TestCase):
    """Test the Data class."""

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        # Date on which there were transactions
        cls.test_date = TEST_DATE
        # Use the direct/non-async API    #
        api = APIDirect()
        # Get API data
        cls.data = api.get_api_data(from_date=cls.test_date, to_date=cls.test_date)

    def test___init__(self):
        """Test Initialization."""
        # Is this a Data class ?
        # Create Data instance
        self.assertIsInstance(self.data, Data)


class TestCache(unittest.TestCase):
    """Test the Cache class with a mock ``Data`` class.

    Use the unittest.mock package to create a mock ``Data`` class.

    """

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        cls.cache = Cache()
        cls.from_date = datetime.date(2021, 8, 7)
        cls.to_date = datetime.date(2021, 8, 10)

        # Mock data to be used in the file
        cls.mock_file_data = "mock cache data"

        # Set up the mock file
        cls.mock_file = mock_open(read_data=cls.mock_file_data)
        cls.patcher = patch("builtins.open", cls.mock_file)
        cls.patcher.start()

    @classmethod
    def tearDownClass(cls):
        # Stop patching 'open'
        cls.patcher.stop()

    def test_write_cache(self):
        """Test the write_cache_data method.

        Use the unittest.mock package to create a mock ``Data`` class.

        """


class TestAPIDirect(unittest.TestCase):
    """A test class for finworks.APIPaths.

    The test date is 2023-12-20.
    """

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        # Re-use the TestAPIPaths.setUpClass fixtures.
        test_api_paths = TestAPIPaths()
        test_api_paths.setUpClass()
        cls.test_date = test_api_paths.test_date
        # Re-use the TestAPIPaths.setUpClass assert_ methods.
        cls.api_paths_class = test_api_paths
        # Result column names for get methods
        cls.model_column_names = test_api_paths.model_column_names
        cls.instrument_column_names = test_api_paths.instrument_column_names
        cls.investor_column_names = test_api_paths.investor_column_names
        cls.position_column_names = test_api_paths.position_column_names
        cls.transaction_column_names = test_api_paths.transaction_column_names

    def setUp(self):
        """Set up test case fixtures."""
        # Use test data to save API hits and time
        self.use_test_data = True
        self.api = APIDirect(use_test_data=self.use_test_data)

        # NOTE: the lack of assert statements in this test is intentional dur to the built in checks in the called methods.

    def test_get_models(self):
        """Test the get_models method."""
        self.api.get_models()

    def test_get_instruments(self):
        """Test the get_instruments method."""
        self.api.get_instruments()

    def test_get_investors(self):
        """Test the get_investors method."""
        self.api.get_investors()

    def test_get_positions(self):
        """Test the get_positions method."""
        self.api.get_positions(date=self.test_date)

    def test_get_transactions(self):
        """Test the get_transactions method."""
        self.api.get_transactions(date=self.test_date)

    def test_get_api_basics_data(self):
        """Test the get_api_basics_data method."""
        models, instruments, investors = self.api.get_api_basics_data()

    def test_get_api_time_series(self):
        """Test the get_api_time_series method."""
        positions, transactions = self.api.get_api_time_series(date=self.test_date)

    def test_get_api_data(self):
        """Test the get_api_data method."""
        data = self.api.get_api_data(date=self.test_date)
        self.assertTrue(isinstance(data, Data))

    def test_get_positions_across_dates(self):
        """test if there is missing positions data on dates."""
        for year in range(2021, 2024):
            for month in range(1, 13):
                day = 7
                date = datetime.date(year, month, day)
                try:
                    positions = self.api.get_positions(date=date)
                except BaseException as e:
                    logger.error(f"Failed for date: {date} with error {e}.")
                # Test positions but do not stop if failed
                try:
                    self.assertTrue(len(positions) > 0, "Response is empty.")
                except AssertionError as e:
                    logger.error(f"Failed for date: {date} with error {e}.")


class Suite(object):
    """Test suite"""

    def __init__(self):
        """Initialization."""
        suite = unittest.TestSuite()

        test_classes = [
            TestSSLCertificates,
            TestAPIPaths,
            TestAPISessionManager,
            TestAPIDirect,
            TestData,
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
