#!/usr/bin/env unittest
# -*- coding: utf-8 -*-
# <nbformat>3.0</nbformat>

"""Test suite for the financial_feed module.

Copyright (C) 2015 Justin Solms <justinsolms@gmail.com>.
This file is part of the fundmanage module.
The fundmanage module can not be modified, copied and/or
distributed without the express permission of Justin Solms.

"""

from abc import ABC
import asyncio
import datetime
import logging
import os
import shutil
import aiohttp
import unittest
import aiounittest
import pandas as pd

# Classes to be tested
from fundmanage3.finworks import APIDirect, APISessionManager, Data
from fundmanage3.finworks import APIPaths
from fundmanage3.finworks import ModelsFrame, InstrumentsFrame, InvestorsFrame
from fundmanage3.finworks import PositionsFrame, TransactionsFrame
from fundmanage3.finworks import Cache

# Define test date ony in a single place
from fundmanage3.finworks import TEST_DATE as MAIN_TEST_DATE

# Get module-named logger.
logger = logging.getLogger(__name__)

# import warnings
# warnings.filterwarnings(
#     action="ignore", message="unclosed", category=ResourceWarning)

# Set up test date
TEST_DATE = MAIN_TEST_DATE
TEST_DATE = Cache.START_DATE

# Use test data fixtures instead of the actual API data
USE_TEST_DATA = True


def sync_runner(async_function):
    """A little cheat to run coroutines synchronously."""
    # Create a new event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Run the async function and wait for it to complete
    loop.run_until_complete(async_function())

    # Close the loop
    loop.close()


@unittest.skip("Test is too slow for actual API data and isn't appropriate here.")
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
        cls.api_class = APISessionManager
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
        cls.transactions_url = (
            f"https://{cls.domain}{cls.transactions_path}?date={TEST_DATE}"
        )
        # Test path and URL and params
        cls.test_path = cls.models_path
        cls.test_url = cls.models_url
        cls.params = {}

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
        async with self.api_class() as api:
            self.assertIsInstance(api.session, aiohttp.ClientSession)
            self.assertIsInstance(api.connector, aiohttp.TCPConnector)

    async def test___aexit__(self):
        """Test __aexit__ method."""
        async with self.api_class() as api:
            pass
        self.assertTrue(api.session.closed)
        self.assertTrue(api.connector.closed)

    @unittest.skip("Test is too slow for actual API data and isn't appropriate here.")
    async def run_then_assert(self, url, params, json_response_fixture=None):
        async with self.api_class() as api:
            response = await api.get_response(url, params, 1)
            self.assertIsInstance(response, list)
            self.assertTrue(len(response) > 0, "Response is empty.")
            self.assertTrue(all(isinstance(item, dict) for item in response))
            if json_response_fixture:
                # NOTE: The line below can only be used if the fixture is up to
                # date with the latest API models data. These models change
                # regularly. Use the fundmanage3.finworks.CollectJSONResponse
                # class to update the fixture files.
                self.assertEqual(response, json_response_fixture)

    @unittest.skip("Test is too slow for actual API data and isn't appropriate here.")
    async def test_get_response_actual(self):
        """Test get_response method with the actual API response."""
        # Use a test URL and params
        test_url = self.test_url
        test_params = self.params
        # Run then asser results
        await self.run_then_assert(test_url, test_params)

    @unittest.skip("Test is too slow for actual API data and isn't appropriate here.")
    async def test_get_retries(self):
        """Test get_retries using a mock ``ClientSession.get`` response."""
        # Use a test path
        test_path = self.test_path

        async with self.api_class() as api:
            response = await api.get_retries(test_path)
            self.assertIsInstance(response, list)
            self.assertTrue(len(response) > 0, "Response is empty.")
            self.assertTrue(all(isinstance(item, dict) for item in response))


class TestModelsFrame(unittest.TestCase):
    """Test suite for the ModelsFrame class."""

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        cls.cls = ModelsFrame

    def setUp(self):
        """Set up test case fixtures."""
        # Use the APIDirect class to get the test data
        self.api = APIDirect(use_test_data=USE_TEST_DATA)
        self.data = self.api.get_models()

    def test___init__(self):
        """Test Initialization."""
        self.assertIsInstance(self.data, ModelsFrame)


class TestInstrumentsFrame(unittest.TestCase):
    """Test suite for the InstrumentsFrame class."""

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        cls.cls = InstrumentsFrame

    def setUp(self):
        """Set up test case fixtures."""
        # Use the APIDirect class to get the test data
        self.api = APIDirect(use_test_data=USE_TEST_DATA)
        self.data = self.api.get_instruments()

    def test___init__(self):
        """Test Initialization."""
        self.assertIsInstance(self.data, InstrumentsFrame)


class TestInvestorsFrame(unittest.TestCase):
    """Test suite for the InvestorsFrame class."""

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        cls.cls = InvestorsFrame

    def setUp(self):
        """Set up test case fixtures."""
        # Use the APIDirect class to get the test data
        self.api = APIDirect(use_test_data=USE_TEST_DATA)
        self.data = self.api.get_investors()

    def test___init__(self):
        """Test Initialization."""
        self.assertIsInstance(self.data, InvestorsFrame)

    def test_merge(self):
        """Test the merge method."""
        # Get models, instruments, investors
        models = self.api.get_models()
        # Merge the data
        merged = self.data.merge(models)
        self.assertIsInstance(merged, InvestorsFrame)
        # Test that the merged DataFrame has the extra columns from the models,
        # instruments and investors DataFrames. This is already tested in the
        # class `check` method.


class ABCTestTimeSeriesFrame(ABC, unittest.TestCase):
    """Abstract test suite for the TimeSeriesFrame child classes."""

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        # Date on which there were transactions
        cls.test_date = TEST_DATE
        cls.cls = None # NOTE: Must be overridden in the child classes

    def setUp(self):
        """Set up test case fixtures."""
        # Use the APIDirect class to get the test data
        self.api = APIDirect(use_test_data=USE_TEST_DATA)
        self.data = None  # NOTE: Must be overridden in the child classes
        self.json_list = None  # NOTE: Must be overridden in the child classes
        self.data_row = None # NOTE: Must be overridden in the child classes

    def test___init__(self):
        """Test Initialization."""
        data = self.cls(self.json_list)
        self.assertIsInstance(data, self.cls)

    def test_slice(self):
        """Test the slice method."""
        date = self.data.date.drop_duplicates().tolist()[0].date()
        # Trivial slice should keep all the data. Not the best test.
        from_date = date
        to_date = date
        boolean_series = from_date <= self.data.date.dt.date <= to_date
        sliced = self.positions.slice(boolean_series)
        self.assertIsInstance(sliced, self.cls)
        pd.testing.assert_frame_equal(self.data, sliced)

    def test_update(self):
        """Test update method."""
        updated = self.data.update(self.data_row)
        self.assertIsInstance(updated, self.cls)
        # Test that the last row of the updated DataFrame is the same as the
        # data row that was appended.
        transaction_id = self.data_row.transaction_id.values[0]
        df1 = updated[updated.transaction_id==transaction_id].reset_index(drop=True)
        df2 = self.data_row.reset_index(drop=True)
        pd.testing.assert_frame_equal(df1, df2)

    def test_merge(self):
        """Test the merge method."""
        # Get models, instruments, investors
        models = self.api.get_models()
        instruments = self.api.get_instruments()
        investors = self.api.get_investors()
        # Merge the data
        merged = self.data.merge(models, instruments, investors)
        self.assertIsInstance(merged, self.cls)
        # Test that the merged DataFrame has the extra columns from the models,
        # instruments and investors DataFrames. This is already tested in the
        # class `check` method.

    def test_concat(self):
        """Test the concat method."""
        updated = self.cls.concat([self.data, self.data_row])
        self.assertIsInstance(updated, self.cls)
        # Test that the last row of the updated DataFrame is the same as the
        # data row that was appended.
        df1 = updated.tail(1).reset_index(drop=True)
        df2 = self.data_row.reset_index(drop=True)
        pd.testing.assert_frame_equal(df1, df2)


class TestPositionsFrame(ABCTestTimeSeriesFrame):
    """Test suite for the TestPositionsFrame class."""

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        super().setUpClass()
        cls.cls = PositionsFrame

    def setUp(self):
        """Set up test case fixtures."""
        super().setUp()
        self.data = self.api.get_positions(date=self.test_date)
        self.assertIsInstance(self.data, PositionsFrame)
        self.json_list = self.data.to_dict(orient="records")
        self.data_date = self.data.date.drop_duplicates().values[0]
        # Make an extra PositionsFrame with a row of new data
        # Use last row of the data as the data row and modify it.
        self.data_row = self.data.iloc[-1].copy()
        # Mods so that the new row passes uniqueness tests
        self.data_row.contract_id = '61173906569'
        self.data_row.client_account_id = '7373856027'
        self.data_row.instrument_id = '889880429'
        self.data_row = self.cls(self.data_row.to_frame().T)


class TestTransactionsFrame(ABCTestTimeSeriesFrame):
    """Test suite for the TestTransactionsFrame class."""

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        super().setUpClass()
        cls.cls = TransactionsFrame

    def setUp(self):
        """Set up test case fixtures."""
        super().setUp()
        self.data = self.api.get_transactions(date=self.test_date)
        self.assertIsInstance(self.data, TransactionsFrame)
        self.json_list = self.data.to_dict(orient="records")
        # Make an extra TransactionsFrame with a row of new data
        # Use last row of the data as the data row and modify it.
        self.data_row = pd.Series()
        # Mods so that the new row passes uniqueness tests
        self.data_row["date"]  = pd.to_datetime('2023-12-13')
        self.data_row["transaction_id"] = '208542467229'
        self.data_row["contract_id"] = '61173906569'
        self.data_row["client_account_id"] = '7373856027'
        self.data_row["instrument_id"] = '889880429'
        self.data_row["is_cashflow"]  = 'No'
        self.data_row["type"] = 'ContributionTransaction'
        self.data_row["sub_type"] = 'Sell'
        self.data_row["currency"] = 'ZAR'
        self.data_row["price"] = 21.2
        self.data_row["units"] = -1.0
        self.data_row["value"] = -21.2
        self.data_row["processed_date"] = pd.to_datetime('2023-12-14')
        self.data_row["description"] = "Sell (Bulk rebalance)"
        self.data_row = self.cls(self.data_row.to_frame().T)


class TestTransactionsFrameIfEmpty(ABCTestTimeSeriesFrame):
    """Test suite for the TestTransactionsFrame class."""

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        super().setUpClass()
        cls.cls = TransactionsFrame

    def setUp(self):
        """Set up test case fixtures."""
        super().setUp()
        self.json_list = []
        self.data = TransactionsFrame(self.json_list)
        self.assertIsInstance(self.data, TransactionsFrame)
        self.data_date = self.test_date
        # Make an extra TransactionsFrame with a row of new data
        # Use last row of the data as the data row and modify it.
        data = self.api.get_transactions(date=self.test_date)
        self.data_row = data.iloc[-1].copy()
        # Mods so that the new row passes uniqueness tests
        self.data_row.transaction_id = '208542467229'
        self.data_row.contract_id = '61173906569'
        self.data_row.client_account_id = '7373856027'
        self.data_row.instrument_id = '889880429'
        self.data_row = self.cls(self.data_row.to_frame().T)

    def test___init__(self):
        """Test Initialization."""
        data = self.cls(self.json_list)
        self.assertIsInstance(data, self.cls)
        self.assertTrue(data.empty)


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
        self.api_obj = APIPaths(use_test_data=USE_TEST_DATA)

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
        self.assertIsInstance(models, ModelsFrame)
        self.assertIsInstance(instruments, InstrumentsFrame)
        self.assertIsInstance(investors, InvestorsFrame)

    async def test_get_models(self):
        """List the available models on the system linked to the Model Manager."""
        async with self.api_obj as api:
            obj = await api.get_models()
            self.assertIsInstance(obj, ModelsFrame)

    async def test_get_instruments(self):
        """List the available instruments on the system."""
        async with self.api_obj as api:
            obj = await api.get_instruments()
            self.assertIsInstance(obj, InstrumentsFrame)

    async def test_get_investors(self):
        """List the available investors on the system."""
        async with self.api_obj as api:
            obj = await api.get_investors()
            self.assertIsInstance(obj, InvestorsFrame)

    async def test_get_positions(self):
        """List the available positions on the system."""
        async with self.api_obj as api:
            obj = await api.get_positions(date=self.test_date)
            self.assertIsInstance(obj, PositionsFrame)

    async def test_get_transactions(self):
        """List the available transactions on the system."""
        async with self.api_obj as api:
            obj = await api.get_transactions(date=self.test_date)
            self.assertIsInstance(obj, TransactionsFrame)


class TestData(unittest.TestCase):
    """Test the Data class."""

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        # Date on which there were transactions
        cls.test_date = TEST_DATE

    def setUp(self):
        """Set up test case fixtures."""
        # Use test data to save API hits and time
        self.api = APIDirect(use_test_data=USE_TEST_DATA)
        # Get API data
        self.data = self.api.get_api_data(from_date=self.test_date, to_date=self.test_date)

    def test___init__(self):
        """Test Initialization."""
        # Is this a Data class ?
        self.assertIsInstance(self.data, Data)




class TestAPIDirect(unittest.TestCase):
    """A test class for finworks.APIPaths.

    The test date is 2023-12-20.
    """

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        cls.test_date = TEST_DATE

    def setUp(self):
        """Set up test case fixtures."""
        # Use test data to save API hits and time
        self.api = APIDirect(use_test_data=USE_TEST_DATA)

        # NOTE: the lack of assert statements in this test is intentional dur to the built in checks in the called methods.

    def test_get_models(self):
        """Test the get_models method."""
        obj = self.api.get_models()
        self.assertIsInstance(obj, ModelsFrame)

    def test_get_instruments(self):
        """Test the get_instruments method."""
        obj = self.api.get_instruments()
        self.assertIsInstance(obj, InstrumentsFrame)

    def test_get_investors(self):
        """Test the get_investors method."""
        obj = self.api.get_investors()
        self.assertIsInstance(obj, InvestorsFrame)

    def test_get_positions(self):
        """Test the get_positions method."""
        obj = self.api.get_positions(date=self.test_date)
        self.assertIsInstance(obj, PositionsFrame)

    def test_get_transactions(self):
        """Test the get_transactions method."""
        obj = self.api.get_transactions(date=self.test_date)
        self.assertIsInstance(obj, TransactionsFrame)

    def test_get_api_basics_data(self):
        """Test the get_api_basics_data method."""
        models, instruments, investors = self.api.get_api_basics_data()
        self.assertIsInstance(models, ModelsFrame)
        self.assertIsInstance(instruments, InstrumentsFrame)
        self.assertIsInstance(investors, InvestorsFrame)

    def test_get_api_time_series(self):
        """Test the get_api_time_series method."""
        positions, transactions = self.api.get_api_time_series(
            from_date=self.test_date, to_date=self.test_date
        )
        self.assertIsInstance(positions, PositionsFrame)
        self.assertIsInstance(transactions, TransactionsFrame)

    def test_get_api_data(self):
        """Test the get_api_data method."""
        data = self.api.get_api_data(from_date=self.test_date, to_date=self.test_date)
        self.assertTrue(isinstance(data, Data))
        self.assertIsInstance(data.models, ModelsFrame)
        self.assertIsInstance(data.instruments, InstrumentsFrame)
        self.assertIsInstance(data.investors, InvestorsFrame)
        self.assertIsInstance(data.positions, PositionsFrame)
        self.assertIsInstance(data.transactions, TransactionsFrame)

    @unittest.skip("Test is too for actual API data and isn't appropriate here.")
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


class TestCache(unittest.TestCase):
    """Test the Cache class."""

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        path = os.path.dirname(__loader__.path)  # This module's file path
        cls.cache_alt_path = os.path.join(path, 'test_finworks_cache')
        # These lines must sync with each other in terms of dates
        cls.increment = 2
        cls.last_date = Cache.START_DATE + datetime.timedelta(days=cls.increment - 1)


    def setUp(self):
        """Set up test case fixtures."""
        self.cache = Cache(alt_path=self.cache_alt_path, use_test_data=True)

    @classmethod
    def tearDownClass(cls) -> None:
        """Tear down class test fixtures."""
        # Delete any cache files created during testing
        if os.path.exists(cls.cache_alt_path):
            # Force the removal of the cache directory and all its contents
            shutil.rmtree(cls.cache_alt_path)

    def test___init__(self):
        """Test Initialization."""
        self.assertIsInstance(self.cache, Cache)

    def test_update(self):
        """Test the update method."""
        # Update the cache
        self.cache.update(increment=self.increment)
        self.assertEqual(self.last_date, self.cache.get_last_cache_date())
        data = self.cache.get_cache_data()
        import ipdb; ipdb.set_trace()
        pass

    def test_batch_update(self):
        """Test the batch_update method."""
        # Update the cache
        self.cache.batch_update(batch_size=2)
        self.assertEqual(self.last_date, self.cache.get_last_cache_date())
        import ipdb; ipdb.set_trace()
        pass

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
