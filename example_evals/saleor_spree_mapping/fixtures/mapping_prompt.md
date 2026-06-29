You are integrating two e-commerce systems. Two repositories are checked out here:

- Saleor (the SOURCE system): `/workspace/saleor`
  Order API schema (GraphQL SDL): `saleor/graphql/schema.graphql` (see `type Order`)
- Spree (the TARGET system): `/workspace/spree`
  Order API schema (OpenAPI JSON): `packages/cli/src/generated/admin-spec.json` (Order schema)

Your task: produce a field mapping for the **Order** entity, from Saleor (source) to Spree (target).

A partially-filled file is waiting at `/workspace/mapping.csv` with three columns:

```
saleor_field,spree_field,transform
```

The `saleor_field` column is already populated. For EACH row, fill in the two empty cells:

- **spree_field**: the name of the equivalent field in the Spree Order schema.
  If the Saleor field has NO equivalent in Spree, leave this BLANK.
- **transform**: how the value would need to be converted, EXACTLY one of:
  - `direct` — copy as-is, only the name differs (target is a scalar, same value)
  - `transform` — target is a scalar but the value must be converted (enum remap, date/number
    format, or extracted from a nested object)
  - `structural` — target is a composite (object/array) needing its own sub-mapping
  - `none` — no equivalent Spree field exists (leave spree_field blank)

Rules:

- Do NOT add, remove, rename, or reorder columns or rows. Only fill the two empty cells per row.
- Use field names exactly as they appear in each schema. Do not invent fields.
- Base your answer only on the two schema files.

Save the completed file back to `/workspace/mapping.csv` when done.
