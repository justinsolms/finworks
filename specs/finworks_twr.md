# API for the portfolio returns and expenses.

## The parties to the requirements

Index solutions - the client  FSP

AOS - the administration FSP

# Reference documents

The AOS / Index Solutions administrative services SLA

## Use Case

1. Under FAIS and in terms of the code of conduct for discretionary FSPs the manager is required to provide detailed information to each client investor regarding their portfolio returns and expenses over time. The manager is also required to perform comparative analysis on product returns and report on portfolio expenses. This requires access to daily historic returns as a function of specified expense streams for each individual portfolio.

2. To monitor and calibrate it own performance the manager must monitor portfolio performance as part of the closing of the loop of asset allocation with performance and expense feedback. This is a statistical process and requires access to daily historic returns as a function of specified expense streams per portfolio product.

3. To successfully compete with other managers and market its own products and services requires access to daily historic returns as a function of specified expense streams per portfolio product.

We have over 3,000 client portfolios to serve on an individual basis. We constantly monitor performance.

Having these services rendered by AOS merely puts us back in the same positions we were in before the switch to Finworks; a position we are far short of now.

We are a highly automated FSP with a single manager. For this reason automated and secure data access is critical.

## Requirements

1. An endpoint to obtain a daily sampled history of portfolio TWR as a function of a selected expense streams primarily at the product level and secondarily at the portfolio level.

2. An endpoint to obtain a daily sampled history of portfolio TWER (Time Weighted Expense Ratio) as a function of a selected expense streams primarily at the product level and secondarily at the portfolio level.

3. Use of the same endpoint infrastructure currently provided by AOS.

## Appendix

It is pointed out here that the TWER may be obtained as the difference between two TWR values where each is each a function of a different set of expense streams. The TWER would then be a function of the set-difference between the two expense streams.
