# 03 Manual Evaluation Rubric

Use `tests/03-answer.md` as the ground-truth reference. Evaluate a chatbot answer to `tests/03.md` by marking each item `Y` or `N`. Do not award partial credit.

## Pass Rule

- **Pass**: all Critical items are `Y`, and at least 6 of 8 Important items are `Y`.
- **Fail**: any Critical item is `N`, or 3+ Important items are `N`.
- **Fatal fail**: answer says overseas platform income is not Korean-reportable merely because it was paid abroad, or says VAT filing is unnecessary solely because customers are overseas.

## Critical

| Metric | Y/N |
|---|---|
| States that a Korean tax resident generally reports worldwide income, including overseas platform/PayPal/foreign-bank receipts. |  |
| Treats repeated digital template/prompt/code sales as likely business income, not automatically miscellaneous income. |  |
| Says lack of business registration does not remove income-tax/VAT reporting duties for already earned revenue. |  |
| Distinguishes income-tax filing from VAT filing and does not collapse them into one issue. |  |
| Explains that zero-rate VAT can apply to qualifying overseas digital-content supplies, but zero-rate still requires VAT reporting. |  |
| Notes that platform structure matters: intermediary/agency vs Merchant of Record/reseller vs license/royalty arrangement. |  |

## Important

| Metric | Y/N |
|---|---|
| Checks whether the 40M KRW figure is gross sales or net settlement after platform/PayPal/refund/VAT-GST deductions. |  |
| Mentions deductible business expenses such as platform fees, payment fees, software/cloud tools, ads, equipment, or outsourcing. |  |
| Requires evidence: platform seller agreement, country-level sales reports, gross/refund/fee settlement data, PayPal and bank records. |  |
| Explains foreign-currency income must be converted to KRW with a defensible date/rate basis. |  |
| Says late business registration should use the real business start date and may create registration-related penalties. |  |
| Mentions late or omitted VAT reporting risks, including zero-rate tax-base reporting penalties where relevant. |  |
| Discusses simplified taxpayer/small-business VAT treatment as conditional, not automatic. |  |
| Separates foreign tax credit from platform fees, PayPal fees, foreign VAT/GST, or sales tax. |  |

## Quality Check

| Metric | Y/N |
|---|---|
| Gives a practical action sequence for reconstructing revenue, classifying platform contracts, registering, and filing. |  |
| Avoids unsupported certainty where facts are missing. |  |
| Includes source-grounded wording or a source section when used in the RAG demo. |  |

## Result

- Critical yes count: `__/6`
- Important yes count: `__/8`
- Quality yes count: `__/3`
- Final result: `Pass / Fail / Fatal fail`
