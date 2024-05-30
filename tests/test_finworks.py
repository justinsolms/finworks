#!/usr/bin/env unittest
# -*- coding: utf-8 -*-
# <nbformat>3.0</nbformat>

"""Test suite for the finworks module.

Copyright (C) 2015 Justin Solms <justinsolms@gmail.com>.
This file is part of the fundmanage module.
The fundmanage module can not be modified, copied and/or
distributed without the express permission of Justin Solms.

"""

from abc import ABC
import logging
import unittest
import pandas as pd

# Classes to be tested
from fundmanage3.finworks import APIClient, ClientInterface
from fundmanage3.finworks import ModelsTask, InstrumentsTask, InvestorsTask
from fundmanage3.finworks import PositionsTask, TransactionsTask
from fundmanage3.finworks import ModelsFrame, InstrumentsFrame, InvestorsFrame
from fundmanage3.finworks import PositionsFrame, TransactionsFrame
from fundmanage3.finworks import


# Define test date ony in a single place
from fundmanage3.finworks import TEST_DATE as MAIN_TEST_DATE

# Get module-named logger.
logger = logging.getLogger(__name__)

# import warnings
# warnings.filterwarnings(
#     action="ignore", message="unclosed", category=ResourceWarning)

# Set up test date
TEST_DATE = MAIN_TEST_DATE

# Use test data fixtures instead of the actual API data
USE_TEST_DATA = True


class TestAPI(unittest.TestCase):
    """Test suite for the ModelsTask class."""

    @classmethod
    def setUpClass(cls) -> None:
        """Set up test class."""

    def setUp(self) -> None:
        """Set up test method."""
        self.api_client = APIClient()

    def test_api(self):
        """Test the API class."""
        self.assertIsInstance(self.api_client, APIClient)
        # Add fetch tasks
        self.api_client.add_task(ModelsTask)
        self.api_client.add_task(InstrumentsTask)
        self.api_client.add_task(InvestorsTask)
        self.api_client.add_task(PositionsTask, date=TEST_DATE)
        self.api_client.add_task(TransactionsTask, date=TEST_DATE)
        # Fetch data
        frames_list = self.api_client.fetch()
        # Check results
        self.assertIsInstance(frames_list, list)
        self.assertEqual(len(frames_list), 5)
        self.assertIsInstance(frames_list[0], ModelsFrame)
        self.assertIsInstance(frames_list[1], InstrumentsFrame)
        self.assertIsInstance(frames_list[2], InvestorsFrame)
        self.assertIsInstance(frames_list[3], PositionsFrame)
        self.assertIsInstance(frames_list[4], TransactionsFrame)

class TestClientInterface(unittest.TestCase):
    """Test suite for the ClientInterface class."""

    @classmethod
    def setUpClass(cls) -> None:
        """Set up test class."""

    def setUp(self) -> None:
        """Set up test method."""
        self.client = ClientInterface()

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

    def get_get_time_series(self):
        """Test the ClientInterface.get_time_series method."""
        # Test the get_time_series method
        time_series_data = self.client.get_time_series()
        positions, transactions = time_series_data
        self.assertIsInstance(positions, PositionsFrame)
        self.assertIsInstance(transactions, TransactionsFrame)

    def test_get_data(self):
        """Test the ClientInterface.get_data method."""
        # Test the get_data method
        data = self.client.get_data()
        models, instruments, investors, positions, transactions = data
        self.assertIsInstance(models, ModelsFrame)
        self.assertIsInstance(instruments, InstrumentsFrame)
        self.assertIsInstance(investors, InvestorsFrame)
        self.assertIsInstance(positions, PositionsFrame)
        self.assertIsInstance(transactions, TransactionsFrame)


class Suite(object):
    """Test suite"""

    def __init__(self):
        """Initialization."""
        suite = unittest.TestSuite()

        test_classes = [
            TestAPI,
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
