# Renewal reset and representative resale notes

## Renewal contract

Renewal replaces the old entitlement with the selected plan. Usage resets to
zero; expiry becomes renewal time plus the selected duration. Zero traffic or
duration retains the selected plan's unlimited meaning. Existing remaining
traffic, expiry and unstarted first-use state do not carry over. The subscription
token/client identity remains unchanged. Bot, mini-app and representative API use
the same engine; the sandbox follows the same expiry rule.

The previous multi-subscription engine intentionally added remaining traffic and
time for usable services, and added unused traffic for unstarted services. Legacy
configs extended the latest local/remote expiry. These were the causes of the
reported inconsistent reset. `tests/test_renewal_reset.py` reproduced both.

A failed remote traffic reset is no longer accepted as success. All configured
nodes must complete renewal before the profile is marked renewed. Panel writes
are not a distributed transaction: a partial remote failure still needs retry;
the existing caller's failure/refund handling applies.

## Private representative accounting

In the mini-app representative report, each purchase unit and each renewal has
its own optional sale price. Empty removes the note; zero means a free sale.
Notes are stored in `rep_sale_prices`, keyed by authenticated buyer, purchase
kind, order and profile. Only an approved purchase belonging to a currently
authorized representative is editable. Notes never affect wallet debits,
tariffs, customer services or other representatives. Admin reports and exports
do not include these private sale/profit fields.

Historical purchase cost uses the net order wallet debit after identified
refunds, then stored clean/quoted order prices. It never uses today's package
price. Newly created orders snapshot price, traffic and duration. Legacy orders
without recoverable price show unknown; unknown costs are excluded from totals
and counted explicitly. Bulk costs distribute the integer remainder so row costs
sum to the order's cost. Purchase ownership follows the original buyer even if
the subscription was transferred to a customer.

Revenue sums entered sale prices. Profit sums sale minus purchase cost only for
rows with both amounts known. Missing sale prices and unknown costs are counted
separately. Totals cover the complete selected purchase-date range even when the
display/export row limit is reached. The representative's Excel includes sale
prices, profits and completeness notes.

Schema changes are additive and applied by `init_db()` on restart; no historical
prices are invented or overwritten and no existing services are reset on deploy.

## Validation

- `python tests/test_renewal_reset.py`
- `python tests/test_rep_accounting.py`
- `python tests/test_rep_sandbox.py`
- Admin and mini-app production builds; mini-app browser checks for Persian
  amounts, save/edit/clear, zero, invalid input, failed save and mobile widths.

`tests/test_rep_api.py` has one pre-existing failure: it expects
`custom_pricing_unavailable` for an unlimited plan without a tariff but receives
`provisioning_failed`. The same failure was reproduced from the unmodified HEAD
in a temporary checkout. Production panels were not contacted during validation.
