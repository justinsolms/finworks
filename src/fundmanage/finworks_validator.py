import json
import os

class JSONValidator:
    """Base class for JSON validation and cleaning."""

    # Name used for data set identification
    NAME = "base"

    # Define keys that are used to uniquely identify each item
    IDENTITY_KEYS = []

    # Define the required keys for the JSON data set
    REQUIRED_KEYS = {}

    # Define keys to drop if any
    KEYS_TO_DROP = []

    # Define keys to rename if any
    KEYS_TO_RENAME = {}

    def __init__(self, json_file):
        self.json_file = json_file
        self.exceptions = []

    def load_json(self):
        with open(self.json_file, 'r') as file:
            return json.load(file)

    def validate_and_clean(self, data):
        cleaned_data = []

        for idx, item in enumerate(data):
            cleaned_item = {}

            # Using the identity keys, construct a unique identifier for each
            # item from the key-value pairs
            identity = ", ".join([f"{key}={item[key]}" for key in self.IDENTITY_KEYS])

            for key, expected_type in self.REQUIRED_KEYS.items():
                if key not in item:
                    self.exceptions.append(f"Missing key '{key}' in item: ({identity})")
                    continue

                value = item[key]
                if isinstance(expected_type, dict):
                    if not isinstance(value, dict):
                        self.exceptions.append(f"Key '{key}' in item: ({identity}) is not a dict")
                        continue

                    cleaned_nested_item = {}
                    for nested_key, nested_type in expected_type.items():
                        if nested_key not in value:
                            self.exceptions.append(f"Missing nested key '{nested_key}' under '{key}' in item: ({identity})")
                            continue
                        if not isinstance(value[nested_key], nested_type):
                            self.exceptions.append(f"Nested key '{nested_key}' under '{key}' in item: ({identity}) has incorrect type.")
                            continue

                        renamed_nested_key = self.KEYS_TO_RENAME.get(nested_key, nested_key)
                        cleaned_nested_item[renamed_nested_key] = value[nested_key]

                    renamed_key = self.KEYS_TO_RENAME.get(key, key)
                    cleaned_item[renamed_key] = cleaned_nested_item
                else:
                    if not isinstance(value, expected_type):
                        self.exceptions.append(f"Key '{key}' in item: ({identity}) has incorrect type.")
                        continue

                    renamed_key = self.KEYS_TO_RENAME.get(key, key)
                    cleaned_item[renamed_key] = value

            for key_to_drop in self.KEYS_TO_DROP:
                cleaned_item.pop(key_to_drop, None)

            cleaned_data.append(cleaned_item)

        return cleaned_data

    def validate_file(self):
        try:
            data = self.load_json()
            cleaned_data = self.validate_and_clean(data)
            if self.exceptions:
                log_file_name = f"validation_exceptions_{self.NAME}.log"
                with open(log_file_name, "w") as log_file:
                    log_file.write("\n".join(self.exceptions))
                raise ValueError(f"Validation errors encountered. Check '{log_file_name}'.")
            return cleaned_data
        except Exception as e:
            raise e


class ModelsValidator(JSONValidator):
    NAME = "models"
    IDENTITY_KEYS = ["Model portfolio id"]
    REQUIRED_KEYS = {
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


class InstrumentsValidator(JSONValidator):
    NAME = "instruments"
    IDENTITY_KEYS = ["Instrument id"]
    REQUIRED_KEYS = {
        "Code": str,
        "Currency": str,
        "ISIN Number": str,
        "Instrument id": int,
        "Instrument provider": str,
        "Instrument type": str,
        "Name": str,
        "Status": str
    }
    KEYS_TO_DROP = []  # Define keys to drop if any
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
    REQUIRED_KEYS = {
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
    }
    KEYS_TO_DROP = []  # Define keys to drop if any
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


class HoldingsValidator(JSONValidator):
    NAME = "holdings"
    IDENTITY_KEYS = ["Client account id", "Contract id", "Instrument id"]
    REQUIRED_KEYS = {
        "Client account id": int,
        "Date": str,
        "Contract id": int,
        "Instrument account number": str,
        "Market Value in Fund Currency": {
            "currency": str,
            "value": str,
            "type": str,
        },
        "Latest available price": {
            "value": str,
            "currency": str,
            "Instrument id": int,
            "type": str,
        },
        "Instrument id": int,
        "Market Value in System Currency": {
            "currency": str,
            "value": str,
            "type": str,
        },
        "Price date": str,
        "Units": {
            "type": str,
            "Instrument id": int,
            "value": str
        },
    }
    KEYS_TO_DROP = ["Instrument account number", "Price date"]
    KEYS_TO_RENAME = {
        "Client account id": "client_account_id",
        "Date": "date"
        "Contract id": "contract_id",
        "Market Value in Fund Currency": "fund_currency_value",
        "Latest available price": "price",
        "Instrument id": "instrument_id",
        "Market Value in System Currency": "system_currency_value",
        "Price date": "price_date",
        "Units": "units",
    }


class TransactionsValidator(JSONValidator):
    NAME = "transactions"
    IDENTITY_KEYS = ["Transaction id"]
    REQUIRED_KEYS = {
        "Transaction id": int,
        "Contract id": int,
        "Client account id": int,
        "Processed date": str,
        "Date": str,
        "Instrument id": int,
        "Description": str,
        "Instrument account number": str,
        "Amount": {
            "currency": str,
            "value": str,
            "type": str,
        },
        "Price": {
            "value": str,
            "currency": str,
            "Instrument id": int,
            "type": str,
        },
        "Units": {
            "value": str,
            "Instrument id": int,
            "type": str,
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
        "Date": "date"
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
        (ModelsValidator("models.json"), "validated_models.json"),
        (InstrumentsValidator("instruments.json"), "validated_instruments.json"),
        (InvestorsValidator("investors.json"), "validated_investors.json"),
        (HoldingsValidator("holdings-2023-12-14.json"), "validated_holdings.json"),
        (TransactionsValidator("transactions-2023-12-14.json"), "validated_transactions.json"),
    ]

    for validator, output_file in validators:
        try:
            validated_data = validator.validate_file()
            with open(output_file, "w") as file:
                json.dump(validated_data, file, indent=4)
            print(f"Validation and cleaning successful. Cleaned data saved to {output_file}.")
        except ValueError as e:
            print(e)
