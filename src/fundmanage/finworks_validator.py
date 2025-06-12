"""
This module provides classes to validate JSON data sets and rename fields
related to financial instruments, model portfolios, investors, holdings, and
transactions.

To use this module, you need to have the following files in the same directory:
- model-portfolios.json
- instruments.json
- investors.json
- holdings.json
- transactions.json

These files may be obtained by running one of the bash scripts in the
test directory:

- finworks-production-get-snippets.sh
- finworks-test-get-snippets.sh
- finworks-training-get-snippets.sh

These scripts will download the JSON files from the Finworks API and save them
to the current directory. They make use of the `curl` GET command to fetch
the data from the API endpoints and are the most reliable and direct way to
get the data in the correct format, test the API endpoints, and ensure
the data to be validated is up-to-date.

Alternatively the classes in this module can be used to validate
the JSON data sets obtained from the Finworks API. The classes will
validate the JSON data sets according to the defined structure and types,
rename the keys according to the defined mapping, and clean the data by
dropping keys that are not in the mapping. The cleaned data is returned as a
list of dictionaries, preserving the original JSON structure and data.

"""


from copy import deepcopy
import json
import os

import pandas as pd

class JSONValidator:
    """Base class for JSON validation and cleaning.

    1. Check JSON data for structure and type using the STRUCTURE_AND_TYPES dict
       noting when there is a nested list of dicts. Do this for all nested
       levels.
    2. Use the KEYS_TO_RENAME_AND_KEEP dict to rename all fields regardless of nesting and keep only those fields, dropping others.
    3. Use IDENTITY_KEYS to construct the item identity for logging.
    4. Log all exceptions per item as log rows identifying the item and the
       exception. Do not raise exception. Only log them.
    5. Output the validated and cleaned data preserving the original JSON
       structure and data

    Note
    ----
    The drop_keys method is only working at the top level keys and will not drop
    nested keys even though the capability is there in the ``drop_keys()``
    method.

    Warning
    -------
    This class will not detect extra keys in the JSON data set. It will only
    check for the required keys and their types.


    """

    # Name used for data set identification
    NAME = "base"

    # Define keys that are used to uniquely identify each item
    IDENTITY_KEYS = []

    # Define the required keys for the JSON data set
    STRUCTURE_AND_TYPES = {}

    # Define keys to rename if any
    KEYS_TO_RENAME_AND_KEEP = {}

    def __init__(self):
        pass

    def load_json(self, json_file):
        with open(json_file, 'r') as file:
            # Detect if the JSON is direct from thePI or if it the value of the
            # `data` key. Raw data from the API is a dict with a `size` key and
            # a `data` key. The data key contains the actual list of items.
            data = json.load(file)
            if isinstance(data, dict) and "data" in data:
                data = data["data"]
            elif not isinstance(data, list):
                raise ValueError(f"Invalid JSON format in {json_file}. Expected a list of items.")
            if not data:
                raise ValueError(f"Empty JSON data in {json_file}. Expected a non-empty list of items.")
            return data

    def validate_key_value(self, item, path, exceptions, key, value):
        """Validate key-value pairs in the JSON data set.

        Together with the ``validate_item`` method, this method will recursively
        validate a nested JSON data set. An example of a nested JSON data
        set is shown below:

        ```
        {
            "key1": "value1",
            "key2": {
                "subkey1": "subvalue1",
                "subkey2": ["item1", "item2"]
            },
            "key3": [
                {"subkey3": "subvalue3"},
                {"subkey4": "subvalue4"}
            ]
        }
        ```
        In the example above, the method will validate the key-value pairs
        recursively, checking if the key exists in the item and if the value
        is of the expected type. If the key is not found, it will log an
        exception with the key path and the expected type. If the value is a
        dictionary, it will recursively validate the nested dictionary. If the
        value is a list, it will recursively validate each item in the list.
        If the value is not of the expected type, it will log an exception with
        the key path and the expected type.

        Parameters
        ----------
        item : dict
            The JSON item to validate.
        path : str
            The path to the current key in the JSON item, used for logging
            exceptions.
        exceptions : list
            A list to collect exceptions encountered during validation.
        key : str
            The key to validate in the JSON item.
        value : type or dict or list
            The expected type or structure of the value for the key in the JSON
            item. If a dict, it represents a nested structure to validate
            against. If a list, it represents a list of items to validate
            against.


        """
        if key in item:
            if isinstance(value, dict):
                if item[key] is None:
                    # FIXME: Allow None values in the data set
                    exceptions.append({"Key": f"{path}{key}", "Issue": f"Expected {type(value)}, got {type(item[key])}"})
                else:
                    exceptions.extend(self.validate_item(item[key], value, path + key + "."))
            elif isinstance(value, list) and isinstance(item[key], list):
                for i, sub_item in enumerate(item[key]):
                    exceptions.extend(self.validate_item(sub_item, value[0], path + key + f"[{i}]."))
            elif not isinstance(item[key], value):
                exceptions.append({"Key": f"{path}{key}", "Issue": f"Expected {value}, got {type(item[key])}"})
        else:
            exceptions.append({"Key": f"{path}{key}", "Issue": "Missing key"})

    def validate_item(self, item, structure, path=""):
        """Validate a single item in the JSON data set.

        Together with the ``validate_key_value`` method, this method will
        recursively validate the JSON data set.
        """
        exceptions = []
        if isinstance(structure, dict):
            for key, value in structure.items():
                self.validate_key_value(item, path, exceptions, key, value)
        else:
            if not isinstance(item, structure):
                exceptions.append({"Key": f"{path}", "Issue": f"Expected {structure}, got {type(item)}"})
        return exceptions

    def validate_and_clean(self, data):
        """Validate and clean the JSON data set.

        This method together with the called methods will validate the JSON data
        set and clean it inplace by recursive methods to reach all nested
        dictionaries.

        The order of work is as follows:
        1. Construct the item identity using the IDENTITY_KEYS
        2. Validate according to the STRUCTURE_AND_TYPES dict
        3. Rename keys, dropping those not in the KEYS_TO_RENAME_AND_KEEP dict

        Parameters
        ----------
        data : list
            The JSON data set to validate and clean.

        Warning
        -------
        This method and its called methods will modify inplace the all the
        original data. Use deepcopy if you need to preserve the original data.
        """

        def rename_keys(item, rename_map):
            if isinstance(item, dict):
                for old_key, new_key in rename_map.items():
                    if old_key in item:
                        item[new_key] = item.pop(old_key)
                for key, value in item.items():
                    rename_keys(value, rename_map)
            elif isinstance(item, list):
                for sub_item in item:
                    rename_keys(sub_item, rename_map)

        def drop_keys(item, keys_to_drop):
            if isinstance(item, dict):
                for key in keys_to_drop:
                    if key in item:
                        item.pop(key)
                for key, value in item.items():
                    drop_keys(value, keys_to_drop)
            elif isinstance(item, list):
                for sub_item in item:
                    drop_keys(sub_item, keys_to_drop)

        def construct_identity(item):
            """Construct the item identity as a dict of key-value pairs."""
            # Return N/A for missing keys
            return {key: item.get(key, "N/A") for key in self.IDENTITY_KEYS}

        cleaned_data = []
        exceptions = []
        for item in data:
            # Validate
            identity = construct_identity(item)
            item_exceptions = self.validate_item(item, self.STRUCTURE_AND_TYPES)
            if item_exceptions:
                # Construct a list of dict for each item exception with the item identity
                item_exceptions = [{**identity, **exception} for exception in item_exceptions]
                exceptions.extend(item_exceptions)

            # Drop keys that are in the STRUCTURE_AND_TYPES dict but not in the
            # KEYS_TO_RENAME_AND_KEEP dict
            # NOTE: This is only working at the top level keys and will not drop
            # nested keys even though the capability is there in `drop_keys`.
            keys_to_drop = set(self.STRUCTURE_AND_TYPES.keys()) - set(self.KEYS_TO_RENAME_AND_KEEP.keys())
            drop_keys(item, keys_to_drop)

            # Rename keys
            rename_keys(item, self.KEYS_TO_RENAME_AND_KEEP)

            cleaned_data.append(item)

        return cleaned_data, exceptions

    def validate_file(self, file_name):
        try:
            data = self.load_json(file_name)
            cleaned_data, exceptions = self.validate_and_clean(data)
            if exceptions:
                log_file_name = f"validation_exceptions_{self.NAME}.csv"
                exceptions_table = pd.DataFrame(exceptions)
                exceptions_table.to_csv(log_file_name, index=False)
                raise ValueError(f"Validation errors encountered. Check '{log_file_name}'.")
            return cleaned_data
        except Exception as e:
            raise e

    def flatten_dict(self, data, parent_key='', sep='_'):
        """Flatten a nested dictionary iteratively.

        Parameters
        ----------
        data : dict
            The dictionary to flatten.
        parent_key : str, optional
            The parent key for the current dictionary, by default ''.
        sep : str, optional
            The separator to use between keys, by default '_'.

        Warning
        -------
        This method will mangle input data. Use deepcopy if you need to preserve
        the original data.

        """
        items = []
        for k, v in data.items():
            new_key = parent_key + sep + k if parent_key else k
            if isinstance(v, dict):
                items.extend(self.flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)

    def flatten_data(self, data):
        """Flatten to a columnar format suitable for the first normal form.

        Warning
        -------
        This method will mangle input data. Use deepcopy if you need to preserve
        the original data.
        """
        flattened_data = []
        for item in data:
            flattened_data.append(self.flatten_dict(item))
        return flattened_data


class ModelsValidator(JSONValidator):
    NAME = "models"
    IDENTITY_KEYS = ["Model portfolio id"]
    STRUCTURE_AND_TYPES = {
        "Splits": [
            {
            "Instrument id": int,
            "Split": {
                "value": str,
                "type": str}
            }
        ],
        "Code": str,
        "Model portfolio id": int,
        "Name": str,
    }
    KEYS_TO_RENAME_AND_KEEP = {
        "Code": "model_ticker",
        "Name": "name",
        "Model portfolio id": "model_portfolio_id",
        "Instrument id": "instrument_id",
        "Splits": "splits",
        "Split": "split",
    }

    def flatten_data(self, data):
        """Flatten to a columnar format suitable for the first normal form.

        This produces a list of dictionaries with the "Splits" list flattened
        and the remaining keys repeated for each item in the "Splits" list. This
        is suitable for converting to a columnar format in the first normal
        form.

        """
        flattened_data = []
        for item in data:
            splits = item.pop("splits")
            for split in splits:
                # Flatten the split dict
                split = self.flatten_dict(split)
                # Add the remaining keys to the split dict
                split.update(item)
                flattened_data.append(split)
        return flattened_data

class InstrumentsValidator(JSONValidator):
    NAME = "instruments"
    IDENTITY_KEYS = ["Instrument id"]
    STRUCTURE_AND_TYPES = {
        "Code": str,
        "Currency": str,
        "ISIN Number": str,
        "Instrument id": int,
        "Instrument provider": str,
        "Instrument provider unique id": int,
        "Instrument type": str,
        "Instrument grouping": str,
        "Name": str,
        "Status": str
    }

    # See InstrumentsFrame docstring for the content
    KEYS_TO_RENAME_AND_KEEP = {
        "Name": "name",
        "ISIN Number": "isin",
        "Instrument id": "instrument_id",
        "Code": "ticker",
        "Instrument type": "instrument_type",
        "Instrument grouping": "instrument_grouping",
        "Instrument provider": "provider",
        "Instrument provider unique id": "provider_id",
        "Status": "status",
        "Currency": "currency",
    }


class InvestorsValidator(JSONValidator):
    NAME = "investors"
    IDENTITY_KEYS = ["Client account id"]
    STRUCTURE_AND_TYPES = {
        "Client account id": int,
        "Contract id": int,
        "Identification number": str,
        "Contract number": str,
        "Description": str,
        "Product": str,
        "Investor name": str,
        "Policy number": str,
        "Status": {
            "identifier": str,
            "active": bool
        },
        "Take On Date": str,
        "Modelportfolio": int,
        "Account number": str,
    }
    KEYS_TO_RENAME_AND_KEEP = {
        "Client account id": "client_account_id",
        "Contract id": "contract_id",
        "Contract number": "contract_number",
        "Identification number": "id_number",
        "Modelportfolio": "model_portfolio_id",
        "Take On Date": "take_on_date",
        "Status": "status",
        "Investor name": "name"
    }


class SpecialTypeValidator(JSONValidator):

    def validate_key_value(self, item, path, exceptions, key, value):
        """Validate key-value pairs in the JSON data set.

        In this ``SpecialTypeValidator`` class the method is overridden to
        handle the special case when the key is "type" in the
        STRUCTURE_AND_TYPES dict.

        The method calls validate_item to recursively validate the nested dict
        that contains a "type" key. This is a special case where the value of
        the "type" key is used to determine the type of the value key in a
        nested dict. This is useful when the JSON data set contains a nested
        dict with a "type" key that selects one of several possible structures
        for the value key. This allows for a flexible structure where the type
        key can be used to determine the structure of the value key in a nested
        dict. For example, the JSON data set may contain a nested dict with a
        "type" key that can be either "Money" or "Unit". The value key will then
        have a different structure depending on the value of the "type" key.

        An example of a nested dict is shown below:

        ```
        {
            "Units": {
                "type": "Money",
                "Money": {
                    "currency": str,
                    "value": str
                },
                "Unit": {
                    "Instrument id": int,
                    "currency": str,
                    "value": str
                }
            }
        }
        ```

        In the example above the type key's value is "Money" and the
        corresponding dict is:

        ```
        {
            "currency": str,
            "value": str
        }
        ```

        Else should the type key's value to be "Unit" the corresponding dict
        would then be:

        ```
        {
            "Instrument id": int,
            "currency": str,
            "value": str
        }
        ```

        This allows for a flexible structure where the type key can be used to
        determine the type of the value key in a nested dict.

        Note
        ----
        If a key's value in the data is null, the method will not raise an
        exception.
        """
        if key in item:
            if isinstance(value, dict):
                if item[key] is None:
                    # FIXME: Allow None values in the data set
                    exceptions.append({"Key": f"{path}{key}", "Issue": f"Expected {type(value)}, got {type(item[key])}"})
                elif "type" in item[key]:
                    type_key = item[key]["type"]
                    if type_key not in value:
                        exceptions.append({"Key": f"{path}{key}", "Issue": f"Invalid type key"})
                        return
                    item_key = item[key]
                    type_structure = value[type_key]
                    exceptions.extend(self.validate_item(item_key, type_structure, path + key + "."))
                else:
                    exceptions.extend(self.validate_item(item[key], value, path + key + "."))
            elif isinstance(value, list) and isinstance(item[key], list):
                for i, sub_item in enumerate(item[key]):
                    exceptions.extend(self.validate_item(sub_item, value[0], path + key + f"[{i}]."))
            elif not isinstance(item[key], value):
                exceptions.append({"Key": f"{path}{key}", "Issue": f"Expected {value}, got {type(item[key])}"})
        else:
            exceptions.append({"Key": f"{path}{key}", "Issue": "Missing key"})


class PositionsValidator(SpecialTypeValidator):
    NAME = "holdings"
    IDENTITY_KEYS = ["Client account id", "Contract id", "Instrument id"]
    STRUCTURE_AND_TYPES = {
        "Client account id": int,
        "Date": str,
        "Contract id": int,
        "Instrument account number": str,
        "Market Value in Fund Currency": {
            "type": str,
            "Money": {
                "currency": str,
                "value": str,
            },
        },
        "Latest available price": {
            "type": str,
            "Price": {
                "Instrument id": int,
                "value": str,
                "currency": str,
            },
        },
        "Instrument id": int,
        "Market Value in System Currency": {
            "type": str,
            "Money": {
                "currency": str,
                "value": str,
            },
        },
        "Price date": str,
        "Units": {
            "type": str,
            "Money": {
                "currency": str,
                "value": str
            },
            "Unit": {
                "Instrument id": int,
                "value": str
            }
        },
    }
    KEYS_TO_RENAME_AND_KEEP = {
        "Date": "date",
        "Contract id": "contract_id",
        "Client account id": "client_account_id",
        "Instrument id": "instrument_id",
        "Market Value in Fund Currency": "market_value",
        "Latest available price": "price",
        "Price date": "price_date",
        "Units": "units",
    }


class TransactionsValidator(SpecialTypeValidator):
    NAME = "transactions"
    IDENTITY_KEYS = ["Transaction id"]
    STRUCTURE_AND_TYPES = {
        "Transaction id": int,
        "Contract id": int,
        "Client account id": int,
        "Processed date": str,
        "Date": str,
        "Instrument id": int,
        "Description": str,
        "Instrument account number": str,
        "Amount": {
            "type": str,
            "Money": {
                "currency": str,
                "value": str,
            },
        },
        "Price": {
            "type": str,
            "Price": {
                "value": str,
                "currency": str,
                "Instrument id": int,
            },
        },
        "Units": {
            "type": str,
            "Money": {
                "currency": str,
                "value": str
            },
            "Unit": {
                "Instrument id": int,
                "value": str
            },
        },
        "Is Cashflow": str,
        "Type": str,
        "Sub type": str,
    }
    KEYS_TO_RENAME_AND_KEEP = {
        "Transaction id": "transaction_id",
        "Contract id": "contract_id",
        "Client account id": "client_account_id",
        "Processed date": "processed_date",
        "Date": "date",
        "Instrument id": "instrument_id",
        "Description": "description",
        "Instrument account number": "instrument_account_number",
        "Amount": "amount",
        "Price": "price",
        "Units": "units",
        "Is Cashflow": "is_cashflow",
        "Type": "type",
        "Sub type": "sub_type",
    }

if __name__ == "__main__":
    validators = [
        # (ModelsValidator(), "model-portfolios.json", "validated_models.json"),
        (InstrumentsValidator(), "instruments.json", "validated_instruments.json"),
        # (InvestorsValidator(), "investors.json", "validated_investors.json"),
        # (PositionsValidator(), "holdings.json", "validated_holdings.json"),
        # (TransactionsValidator(), "transactions.json", "validated_transactions.json"),
    ]

    for validator, input_file, output_file in validators:
        try:
            validated_data = validator.validate_file(input_file)
        except ValueError as e:
            print(e)
        else:
            flattened_data = validator.flatten_data(validated_data)
            with open(output_file, "w") as file:
                json.dump(flattened_data, file, indent=4)
            print(f"Validation and cleaning successful. Cleaned data saved to {output_file}.")

