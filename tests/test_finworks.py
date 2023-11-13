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
import aiohttp
import unittest
import aiounittest
import pandas as pd

# Classes to be tested
from fundmanage3.finworks import APISessionManager
from fundmanage3.finworks import APIPaths
from fundmanage3.finworks import Cache

# import warnings
# warnings.filterwarnings(
#     action="ignore", message="unclosed", category=ResourceWarning)


class TestSSLCertificates(aiounittest.AsyncTestCase):
    """Class test template."""

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        # Use the _APIPaths class to set up fixtures and verify certificates
        api = APIPaths()
        # URL
        hostname = APIPaths._DOMAIN
        path = APIPaths._models_path
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


class TestAPI(aiounittest.AsyncTestCase):
    """Direct API query, response and result checking."""

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        hostname = APISessionManager._DOMAIN
        path = APIPaths._models_path  # Use as a test path
        cls.path = path
        cls.url = f"https://{hostname}{path}"

    @classmethod
    def tearDownClass(cls):
        """Tear down class test fixtures."""
        pass

    def setUp(self):
        """Set up one test."""
        pass

    def tearDown(self):
        """tear down test case fixtures."""
        pass

    async def test___init__(self):
        """Test Initialization."""
        async with APISessionManager() as api:
            self.assertIsInstance(api.session, aiohttp.client.ClientSession)

    async def test__get_response(self):
        """Get some data over the API."""
        async with APISessionManager() as api:
            response = await api.get_response(self.url, {})
            # Unpack the response form the response_url.
            response, _ = response
            self.assertIsInstance(response, list)
            self.assertIsInstance(response[0], dict)

    async def test__get_retries(self):
        """Get with the possibility of retries to the API."""
        async with APISessionManager() as api:
            response = await api.get_retries(self.path)
            self.assertIsInstance(response, list)
            self.assertIsInstance(response[0], dict)


class TestAPIPaths(aiounittest.AsyncTestCase):
    """ """

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        pass

    @classmethod
    def tearDownClass(cls):
        """Tear down class test fixtures."""
        pass

    def setUp(self):
        """Set up one test."""
        pass

    def tearDown(self):
        """tear down test case fixtures."""
        pass

    async def test___init__(self):
        """Test Initialization."""
        # Is this a subclass of _API?
        async with APIPaths() as api:
            self.assertIsInstance(api, APIPaths)

    async def test_get_model_portfolios(self):
        """List the available models on the system linked to the Model Manager."""
        index_names = ["model_ticker", "model_portfolio_id", "name"]
        async with APIPaths() as api:
            response = await api.get_models()
            self.assertIsInstance(response, pd.DataFrame)
            self.assertEqual(index_names, response.columns.to_list()[0:3])

    def test_runner(self):
        """Get multiple requests tasks in the runner."""
        # Data Gathering awaitable

        async def get_results():
            async with APIPaths() as api:
                tasks_list = list()
                tasks_list.append(api.get_models())
                tasks_list.append(api.get_instruments())
                results = await asyncio.gather(*tasks_list)
            return results

        # Run all tasks
        models, instruments = asyncio.run(get_results())

    # TODO: Write the rest of the `get` method tests


class TestCache(unittest.TestCase):
    """Get, integrate and cache data in a standard column format."""

    @classmethod
    def setUpClass(cls):
        """Set up class test fixtures."""
        cls.cache = Cache()
        cls.from_date = datetime.date(2021, 8, 7)
        cls.to_date = datetime.date(2021, 8, 10)

    def setUp(self):
        """Set up one test."""
        pass

    def test_cache_api_equality(self):
        """Get cache data and verify against the API data.

        This only works if the cache has the data in the test date range.
        """
        cache_data = self.cache.get_cache_data(self.from_date, self.to_date)
        api_data = self.cache.get_api_data(self.from_date, self.to_date)
        # Do not test basics data equality as this can change at any moment.
        pass
        # Test time series equality
        pd.testing.assert_frame_equal(cache_data.positions, api_data.positions)
        pd.testing.assert_frame_equal(cache_data.transactions, api_data.transactions)


class Suite(object):
    """Test suite"""

    def __init__(self):
        """Initialization."""
        suite = unittest.TestSuite()

        test_classes = [
            TestSSLCertificates,
            TestAPI,
            TestAPIPaths,
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
