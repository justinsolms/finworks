# %%
# Import the necessary libraries
import pandas as pd
from fundmanage.finworks import Cache


# %%
# Load the client list
cache = Cache()
last_date = cache.last_date()
data = cache.get_cache_data(from_date=last_date, to_date=last_date)
investors = data.investors

# %%
# Mrs Leigh-Anne Malherbe, ID# 6403050214089
investor = investors[investors['id_number'] == '6403050214089']
# Portfolio of Mrs Leigh-Anne Malherbe are as follows:
# ITRSVPGRO - Client account ID: 236952440065
# IDXDISGROA - Client account ID: 7814588161
client_account_ids = investor['client_account_id'].to_list()
positions = data.positions[data.positions['client_account_id'].isin(client_account_ids)]
values = positions[['ticker', 'value']].set_index('ticker')
nav = positions.value.sum()
weights = values / nav


# %%
# Client list for Salomy
client_list = investors[["name", "id_number", "contract_id", "status", "active"]
    ].sort_values(by=["status", "active", "name"]
    ).drop_duplicates()
client_list.to_excel("~/Downloads/client_list.xlsx", index=False)

# %%
