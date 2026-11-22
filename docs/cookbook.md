# map-conform cookbook

Each recipe shows a spec, the records a tap sends, and the records map-conform emits. Every
example here is run by the test suite (`tests/test_cookbook.py`), so what you read is what
the mapper does. Keys and options are listed in the [spec reference](spec-reference.md).

The blocks are tagged: `cookbook:spec` is the conform spec, `cookbook:input` the tap's
records (their properties are strings unless a `cookbook:schema` block types them),
`cookbook:settings` any plugin settings, and `cookbook:output` what the mapper writes.

## A CSV export

tap-csv reads every value as text. Declare the types you want; the casts clean the text on
the way: currency symbols and thousands separators, accounting negatives, percentages,
yes/no words, US dates and null tokens. Column names are conformed to snake_case.

```yaml cookbook:spec
version: 1
streams:
  Orders Export:
    columns:
      Order ID: {name: order_id, type: int64, nullable: false}
      Amount ($): {type: "decimal(12,2)", parse: {parens_negative: true}}
      Discount %: {type: "decimal(6,4)", parse: {percent: divide}}
      Paid?: {type: boolean}
      Order Date: {type: date, parse: {formats: ["%m/%d/%Y", iso]}}
      Customer Email: {type: string}
```

```json cookbook:input
[
  {"Order ID": " 1001 ", "Amount ($)": "$1,234.50", "Discount %": "15%", "Paid?": "Yes",
   "Order Date": "03/14/2026", "Customer Email": "ann@example.com"},
  {"Order ID": "1002", "Amount ($)": "(12.00)", "Discount %": "0%", "Paid?": "no",
   "Order Date": "2026-03-15", "Customer Email": "N/A"}
]
```

```json cookbook:output
[
  {"order_id": 1001, "amount": "1234.50", "discount": "0.1500", "paid": true, "order_date": "2026-03-14", "customer_email": "ann@example.com"},
  {"order_id": 1002, "amount": "-12.00", "discount": "0.0000", "paid": false, "order_date": "2026-03-15", "customer_email": null}
]
```

## A spreadsheet (XLSX) export

Spreadsheet taps send whole numbers as floats, dates as serial numbers, binary float
artefacts, and error cells as text. Excel serials are a date format of their own, and
`#N/A` is one of the default null tokens.

```yaml cookbook:spec
version: 1
streams:
  inventory:
    columns:
      SKU: {type: string}
      Qty: {type: int32}
      Unit Cost: {type: "decimal(10,2)"}
      Received: {type: date, parse: {formats: [excel_serial, iso]}}
      Weight (kg): {type: "decimal(8,3)", on_error: "null"}
```

```json cookbook:schema
{"SKU": {"type": "string"}, "Qty": {"type": "number"}, "Unit Cost": {"type": "number"},
 "Received": {"type": ["number", "string"]}, "Weight (kg)": {"type": ["number", "string"]}}
```

```json cookbook:input
[
  {"SKU": "A-1", "Qty": 3.0, "Unit Cost": 0.30000000000000004, "Received": 46095.0,
   "Weight (kg)": 1.5},
  {"SKU": "B-2", "Qty": 12.0, "Unit Cost": 2.5, "Received": "2026-03-01",
   "Weight (kg)": "#N/A"}
]
```

```json cookbook:output
[
  {"sku": "A-1", "qty": 3, "unit_cost": "0.30", "received": "2026-03-14", "weight_kg": "1.500"},
  {"sku": "B-2", "qty": 12, "unit_cost": "2.50", "received": "2026-03-01", "weight_kg": null}
]
```

## Epoch timestamps

APIs often send times as seconds or milliseconds since 1970. Say which; the result is a UTC
timestamp.

```yaml cookbook:spec
version: 1
streams:
  events:
    columns:
      created: {type: timestamptz, parse: {formats: [epoch_s]}}
      updated_ms: {type: timestamptz, parse: {formats: [epoch_ms]}}
      seen: {type: timestamptz, parse: {formats: [iso, epoch_s]}}
```

```json cookbook:schema
{"created": {"type": "integer"}, "updated_ms": {"type": "integer"}, "seen": {"type": "string"}}
```

```json cookbook:input
[
  {"created": 1773480413, "updated_ms": 1773480413123, "seen": "2026-03-14T10:26:53+01:00"},
  {"created": 1773480413, "updated_ms": 1773480413999, "seen": "1773480413"}
]
```

```json cookbook:output
[
  {"created": "2026-03-14T09:26:53.000000Z", "updated_ms": "2026-03-14T09:26:53.123000Z", "seen": "2026-03-14T09:26:53.000000Z"},
  {"created": "2026-03-14T09:26:53.000000Z", "updated_ms": "2026-03-14T09:26:53.999000Z", "seen": "2026-03-14T09:26:53.000000Z"}
]
```

## Masking personal data

Hash an email with a salt (keep the salt out of the file with `${env:...}` or `spec_vars`),
show only the last digits of a phone number, drop a national ID, keep only the year of a
birth date, and replace a card number with a keyed token that is stable across runs. A
`when` masks a column only on some rows.

```yaml cookbook:spec
version: 1
streams:
  customers:
    columns:
      email: {transform: {hash: {salt: "${salt}"}}}
      phone: {transform: {mask: {keep_last: 4}}}
      national_id: {transform: set_null}
      birth_date: {type: date, transform: [cast, redact_date]}
      card: {transform: {tokenize: "${token_key}"}}
      country: {type: string}
      city: {type: string, transform: {mask_hidden: "***"}, when: "country == 'DE'"}
```

```json cookbook:settings
{"spec_vars": {"salt": "pepper", "token_key": "k-2026"}}
```

```json cookbook:input
[
  {"email": "ann@example.com", "phone": "+1 555 0100", "national_id": "123-45-6789",
   "birth_date": "1990-07-04", "card": "4111111111111111", "country": "DE", "city": "Berlin"},
  {"email": "bob@example.com", "phone": "+1 555 0199", "national_id": "987-65-4321",
   "birth_date": "1985-12-31", "card": "4111111111111111", "country": "US", "city": "Austin"}
]
```

```json cookbook:output
[
  {"email": "831740710d6a8225c6ad8e71610353afdfcf9f6a3caa448dc11ab17a513081c2", "phone": "*******0100", "national_id": null, "birth_date": "1990-01-01", "card": "ae2f4debe1d2b4d9d79a4b89147c674db6fca8990e5c1d7911c67ca551961083", "country": "DE", "city": "***"},
  {"email": "40f27281a6f2d75f9690f415970debe57e538178a2ef93d532ee09f0fb0c90da", "phone": "*******0199", "national_id": null, "birth_date": "1985-01-01", "card": "ae2f4debe1d2b4d9d79a4b89147c674db6fca8990e5c1d7911c67ca551961083", "country": "US", "city": "Austin"}
]
```

## Derived columns and a filter

A column can be computed from others, by their conformed names and typed values. The filter
drops the rows where it is false; it sees the same names.

```yaml cookbook:spec
version: 1
streams:
  order_lines:
    filter: total > 0
    columns:
      Qty: {type: int32}
      Price: {type: "decimal(10,2)"}
      total: {type: "decimal(12,2)", expr: qty * price}
      size: {type: string, expr: "'bulk' if qty >= 100 else 'retail'"}
```

```json cookbook:input
[
  {"Qty": "3", "Price": "2.50"},
  {"Qty": "0", "Price": "9.99"},
  {"Qty": "120", "Price": "1.10"}
]
```

```json cookbook:output
[
  {"qty": 3, "price": "2.50", "total": "7.50", "size": "retail"},
  {"qty": 120, "price": "1.10", "total": "132.00", "size": "bulk"}
]
```

## Nested JSON with a declared shape

Declare the shape of a nested object and flatten it: the columns and their types come from
the shape, so the output does not change when the tap's schema drifts. A member's `default`
says how a missing or empty value lands, and members the shape does not declare are dropped
(and counted in the metrics).

```yaml cookbook:spec
version: 1
defaults: {naming: {collapse: false}}
streams:
  users:
    columns:
      profile:
        flatten: true
        shape:
          type: object
          properties:
            name: {type: string}
            tags: {type: array, items: {type: string}, default: []}
            prefs: {type: object, default: {}}
```

```json cookbook:schema
{"id": {"type": "string"}, "profile": {"type": "object"}}
```

```json cookbook:input
[
  {"id": "1", "profile": {"name": "Ann", "tags": ["vip"], "prefs": {"lang": "en"}}},
  {"id": "2", "profile": {"name": "Bob", "tags": [], "unknown": true}},
  {"id": "3"}
]
```

```json cookbook:output
[
  {"id": "1", "profile__name": "Ann", "profile__tags": ["vip"], "profile__prefs": "{\"lang\": \"en\"}"},
  {"id": "2", "profile__name": "Bob", "profile__tags": [], "profile__prefs": "{}"},
  {"id": "3", "profile__name": null, "profile__tags": [], "profile__prefs": "{}"}
]
```

## Moving from SDK stream maps

The settings of meltano-map-transformer work unchanged: they are translated into a spec at
start-up, with defaults that keep the old output. `map-conform spec import --stream-maps config.json` writes the translation as a spec file, so you can switch over and then use the
rest of the spec.

```yaml cookbook:spec
version: 1
```

```json cookbook:settings
{"stream_maps": {"customers": {"email_hash": "md5(email)", "domain": "email.split('@')[1]",
                               "email": null}}}
```

```json cookbook:input
[{"id": "1", "email": "ann@example.com"}]
```

```json cookbook:output
[
  {"id": "1", "email_hash": "257c57037d384ae37ea27a07e8a01665", "domain": "example.com"}
]
```
