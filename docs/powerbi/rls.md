# Row-level security (RLS)

Goal: each country controller sees only their own entity; group finance sees everything.

## 1. The mapping table

`dim_user_entity` (loaded from `export/powerbi_export/dim_user_entity.parquet`) has two columns:
`user_principal_name`, `entity_id`. Use the literal `ALL` for group users. **Replace the sample e-mails** with real
user principal names. Do not create relationships from this table.

| user_principal_name | entity_id |
|---|---|
| group.finance@example.com | ALL |
| controller.fr@example.com | E01 |
| controller.us@example.com | E04 |
| controller.us@example.com | E05 |

## 2. Create the role

Modeling > Manage roles > New role `EntityController`. Table `dim_entity`, filter expression:

```dax
VAR me = USERPRINCIPALNAME ()
VAR allowed =
    SELECTCOLUMNS (
        FILTER ( dim_user_entity, dim_user_entity[user_principal_name] = me ),
        "e", dim_user_entity[entity_id]
    )
RETURN
    "ALL" IN allowed || dim_entity[entity_id] IN allowed
```

Because every fact table filters through `dim_entity`, this one expression secures the whole model (ledger, trial
balance, budgets, receivables, bank reconciliation, forecast, exceptions).

**Also secure `dim_customer`** (it is deliberately not related to `dim_entity`, to avoid an ambiguous filter path, so it needs its own filter
or customer IDs from other entities would still appear in slicers). In the same role add a filter on `dim_customer` with the same expression,
replacing the last line:

```dax
VAR me = USERPRINCIPALNAME ()
VAR allowed =
    SELECTCOLUMNS (
        FILTER ( dim_user_entity, dim_user_entity[user_principal_name] = me ),
        "e", dim_user_entity[entity_id]
    )
RETURN
    "ALL" IN allowed || dim_customer[entity_id] IN allowed
```

## 3. Test it

Modeling > View as > `EntityController` > tick "Other user" and type `controller.us@example.com`.
Expected: only Meridian Inc East and Meridian Inc West appear in every slicer and visual, and `[Revenue]` is the sum of
those two entities. Then test `group.finance@example.com` (everything) and an unmapped user (empty report - correct).

## 4. Things to know

* RLS only takes effect in the **Power BI service** (workspace role assignments or app audience); in Desktop it is a test tool.
* Members of the workspace with **Contributor** or higher bypass RLS - give viewers the Viewer role.
* Unmapped users see nothing. That is the safe default; do not "fix" it with a catch-all role.
* STATUS: this DAX has not been executed (Power BI Desktop could not be run where this was built). Test with "View as".
