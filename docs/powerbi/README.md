# Building the Power BI report (about half a day)

Everything is prepared; what is left is the part that has to happen in Power BI Desktop (Windows).

> **What is verified and what is not.** The data, the DAX column references, the KPI targets and the model design are
> tested in this repository. The `.pbix` itself and the DAX *execution* are not - Power BI Desktop could not be run where
> this project was built. `validation.md` exists so you can prove the measures right in ten minutes.

## Steps

1. **Build the data** (once, ~1 minute): `python run_pipeline.py` then open `export/powerbi_export/` (Parquet files).
2. **Power BI Desktop > File > Options > Current file > Data load**: untick **Auto date/time**.
3. **Home > Transform data > Manage parameters > New**: text parameter `DataFolder` = the full path to
   `export/powerbi_export\` (with a trailing backslash).
4. **Load the 19 tables** with the M template in `data_model.md` (one blank query per table, change the file name).
5. **Model view**: create the relationships from the diagram in `data_model.md` (all many-to-one, single direction; do **not** relate `dim_customer` to `dim_entity`).
   Right-click `dim_date` > **Mark as date table** > `date_key`. Sort `month_short` by `month`.
6. **Create a `_Measures` table** (Home > Enter data, one empty column, name it, then delete the column) and paste the
   measures from `measures.dax` one by one (new measure > paste). Create the `Variance Bridge` table with New table.
7. **View > Themes > Browse for themes** > `theme.json`.
8. **Build the 7 pages** from `report_pages.md`.
9. **Validate**: work through `validation.md` (32 KPIs). Fix any measure that disagrees.
10. **Security** (optional): follow `rls.md`.
11. **Share**: see below.

## Sharing options

* Publishing to the Power BI service and "Publish to web" generally require a **work or school account**; a personal
  e-mail often cannot. Check before promising a live link.
* If you cannot publish: export each page to **PDF** (File > Export) and take screenshots into `docs/figures/powerbi/`,
  then commit the `.pbix` (Parquet files are not needed if you use "Include data" - or tell reviewers to run the pipeline).
* The `docs/figures/` charts in this repo are **Python previews**, not Power BI visuals; do not present them as such.

## Files

| File | Purpose |
|---|---|
| `data_model.md` | tables, grain, relationships, loading |
| `measures.dax` | 56 measures |
| `report_pages.md` | page-by-page visual spec |
| `theme.json` | colour theme |
| `rls.md` | row-level security |
| `expected_kpis.csv`, `validation.md` | targets to check the measures against (generated) |
