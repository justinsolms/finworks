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
from fundmanage3.finworks import API
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
        self.api = API()

    def test_api(self):
        """Test the API class."""
        self.assertIsInstance(self.api, API)
        # Test fetching the models
        self.api.add_task(ModelsTask)
        self.api.add_task(InstrumentsTask)
        self.api.add_task(InvestorsTask)
        self.api.add_task(PositionsTask, date=TEST_DATE)
        self.api.add_task(TransactionsTask, date=TEST_DATE)
        frames_list = self.api.fetch()
        # for frame in frames_list:
        #     print(frame.data)
        self.assertIsInstance(frames_list, list)
        self.assertEqual(len(frames_list), 5)
        self.assertIsInstance(frames_list[0], ModelsFrame)
        self.assertIsInstance(frames_list[1], InstrumentsFrame)
        self.assertIsInstance(frames_list[2], InvestorsFrame)
        self.assertIsInstance(frames_list[3], PositionsFrame)
        self.assertIsInstance(frames_list[4], TransactionsFrame)





