import json
import os

class JSONValidator:
    """Base class for JSON validation and cleaning.

    1. Check JSON data for structure and type using the STRUCTURE_AND_TYPES dict
       noting when there is a nested list of dicts. Do this for all nested
       levels.
    2. Use the KEYS_TO_RENAME dict to rename all fields regardless of nesting.
    3. Drop keys as per the KEYS_TO_DROP list
    4. Use IDENTITY_KEYS to construct the item identity for logging.
    5. Log all exceptions per item as log rows identifying the item and the
       exception. Do not raise exception. Only log them.
    6. Output the validated and cleaned data preserving the original JSON
       structure and data

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

    # Define keys to drop if any
    KEYS_TO_DROP = []

    # Define keys to rename if any
    KEYS_TO_RENAME = {}

    def __init__(self):
        pass

    def load_json(self, json_file):
        with open(json_file, 'r') as file:
            return json.load(file)

    def validate_key_value(self, item, path, exceptions, key, value):
        if key in item:
            if isinstance(value, dict):
                exceptions.extend(self.validate_item(item[key], value, path + key + "."))
            elif isinstance(value, list) and isinstance(item[key], list):
                for i, sub_item in enumerate(item[key]):
                    exceptions.extend(self.validate_item(sub_item, value[0], path + key + f"[{i}]."))
            elif not isinstance(item[key], value):
                exceptions.append(f"- {path}{key}: Expected {value}, got {type(item[key])}")
        else:
            exceptions.append(f"- {path}{key}: Missing key")

    def validate_item(self, item, structure, path=""):
        exceptions = []
        if isinstance(structure, dict):
            for key, value in structure.items():
                self.validate_key_value(item, path, exceptions, key, value)
        else:
            if not isinstance(item, structure):
                exceptions.append(f"- {path}: Expected {structure}, got {type(item)}")
        return exceptions

    def validate_and_clean(self, data):

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
            return ", ".join([f"{key}={item.get(key, 'N/A')}" for key in self.IDENTITY_KEYS])

        cleaned_data = []
        exceptions = []
        for item in data:
            identity = construct_identity(item)
            item_exceptions = self.validate_item(item, self.STRUCTURE_AND_TYPES)
            if item_exceptions:
                exceptions.append(f"Item identity: ({identity}):")
                exceptions.extend(item_exceptions)
            rename_keys(item, self.KEYS_TO_RENAME)
            drop_keys(item, self.KEYS_TO_DROP)
            cleaned_data.append(item)

        return cleaned_data, exceptions

    def validate_file(self, file_name):
        try:
            data = self.load_json(file_name)
            cleaned_data, exceptions = self.validate_and_clean(data)
            if exceptions:
                log_file_name = f"validation_exceptions_{self.NAME}.log"
                with open(log_file_name, "w") as log_file:
                    log_file.write("\n".join(exceptions))
                raise ValueError(f"Validation errors encountered. Check '{log_file_name}'.")
            return cleaned_data
        except Exception as e:
            raise e

    def flatten_dict(self, d, parent_key='', sep='_'):
        """Flatten a nested dictionary iteratively.

        Parameters
        ----------
        d : dict
            The dictionary to flatten.
        parent_key : str, optional
            The parent key for the current dictionary, by default ''.
        sep : str, optional
            The separator to use between keys, by default '_'.
        """
        items = []
        for k, v in d.items():
            new_key = parent_key + sep + k if parent_key else k
            if isinstance(v, dict):
                items.extend(self.flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)

    def flatten_data(self, data):
        """Flatten to a columnar format suitable for the first normal form."""
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
    KEYS_TO_DROP = []  # Define keys to drop if any
    KEYS_TO_RENAME = {
        "Splits": "splits",
        "Instrument id": "instrument_id",
        "Split": "split",
        "Code": "code",
        "Model portfolio id": "model_portfolio_id",
        "Name": "name",
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
        "Instrument type": str,
        "Name": str,
        "Status": str
    }
    KEYS_TO_DROP = ["Instrument provider unique id"]  # Define keys to drop if any
    KEYS_TO_RENAME = {
        "Code": "code",
        "Currency": "currency",
        "ISIN Number": "isin_number",
        "Instrument id": "instrument_id",
        "Instrument provider": "instrument_provider",
        "Instrument type": "instrument_type",
        "Name": "name",
        "Status": "status"
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
    KEYS_TO_DROP = ["Account number"]  # Define keys to drop if any
    KEYS_TO_RENAME = {
        "Policy number": "policy_number",
        "Contract number": "contract_number",
        "Contract id": "contract_id",
        "Product": "product",
        "Take On Date": "take_on_date",
        "Description": "description",
        "Identification number": "identification_number",
        "Status": "status",
        "Modelportfolio": "model_portfolio",
        "Client account id": "client_account_id",
        "Investor name": "investor_name"
    }


class SpecialTypeValidator(JSONValidator):

    def validate_key_value(self, item, path, exceptions, key, value):
        """Validate key-value pairs in the JSON data set.

        The method is overridden to handle the special case when the key is
        "type" in the STRUCTURE_AND_TYPES dict.

        IN a nested dict the type key is used to determine the type of the of the
        value key. For example:

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

        The type key's value is read from the dict. The value is used
        to select the corresponding dict from the STRUCTURE_AND_TYPES dict. This
        dict is used in the usual manner to validate the nested dict. IN the
        example above the type key's value is "Money" and the corresponding dict
        is:

        {
            "currency": str,
            "value": str
        }

        The method calls validate_item to recursively validate the nested dict.


        """
        if key in item:
            if isinstance(value, dict):
                if "type" in item[key]:
                    type_key = item[key]["type"]
                    if type_key not in value:
                        exceptions.append(f"- {path}{key}: Invalid type key")
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
                exceptions.append(f"- {path}{key}: Expected {value}, got {type(item[key])}")
        else:
            exceptions.append(f"- {path}{key}: Missing key")


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
    KEYS_TO_DROP = ["Instrument account number", "Price date"]
    KEYS_TO_RENAME = {
        "Client account id": "client_account_id",
        "Date": "date",
        "Contract id": "contract_id",
        "Market Value in Fund Currency": "fund_currency_value",
        "Latest available price": "price",
        "Instrument id": "instrument_id",
        "Market Value in System Currency": "system_currency_value",
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
    KEYS_TO_DROP = []  # Define keys to drop if any
    KEYS_TO_RENAME = {
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
        (ModelsValidator(), "models.json", "validated_models.json"),
        (InstrumentsValidator(), "instruments.json", "validated_instruments.json"),
        (InvestorsValidator(), "investors.json", "validated_investors.json"),
        (PositionsValidator(), "holdings-2023-12-14.json", "validated_holdings.json"),
        (TransactionsValidator(), "transactions-2023-12-14.json", "validated_transactions.json"),
    ]

    for validator, input_file, output_file in validators:
        try:
            validated_data = validator.validate_file(input_file)
            flattened_data = validator.flatten_data(validated_data)
            with open(output_file, "w") as file:
                json.dump(flattened_data, file, indent=4)
            print(f"Validation and cleaning successful. Cleaned data saved to {output_file}.")
        except ValueError as e:
            print(e)
