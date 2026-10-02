# Sprint notes

Open questions and decisions for the mangrove sprint. Keep it short and dated.

## The first experiment (template)

The example is `data/experiments/synthetic_example.yml`. It compares mangrove extent between two
comparable source dates within an agreed area.

- **Area:** not chosen.
- **Sources:** not chosen. Fill `data/source_catalog.yml` from each publisher.
- **Method:** **pending**. The lab produces no analysis result until the team agrees one.
- **Independent reference result:** not chosen. We need one checked answer to compare against.

## Contract gaps found (2 October 2026)

1. **No mangrove pack.** The packs advertised are `risk` and `food-security`.
2. **Mangrove polygons.** The `vector` kind accepts Point features only. Mangrove extent polygons
   have no contribution kind.
3. **Mangrove rasters.** The `raster` kind expects `hazard_`, `risk_` or `vulnerability_` class maps
   (0-5), or a `population_` count grid. An extent or carbon raster is neither. The lab will not
   rename or reclassify a mangrove raster to make it fit.
4. **Boundary upload.** This is not a contribution kind. Areas come from OpenStreetMap.
5. **Analysis.** `compute_run` is planned and not available. No REST route for questions or
   analysis is documented.

`msl check` reports gaps 2 and 3 as blocking, and gap 1 as a note.

## Questions for SIG

- Which server or branch will support the mangrove workflow? What formats will it accept, and
  which analytical operations?
- Will there be a mangrove contribution kind (polygon extent, an extent or carbon raster) and a
  mangrove pack?
- Are there REST routes beyond contribution submit and status, for capabilities, a list of my
  contributions, questions or analysis?
- Can `/api/contribute` add the documented `WWW-Authenticate` header to its 401?
- How do we register an app client and callback on AuthKit, if a browser login is needed?
- Visibility:
  - Is auto-approve on for the sprint?
  - Who sees a `staged` contribution?
  - Can a submitter withdraw an approved one?
- Versioning: a name cannot be overwritten. What is the supported way to publish a corrected
  version?
- Is there an idempotency key, or a list route, to resolve a submit that timed out?

## Questions for the sprint team

- Which area, source and independently checked reference result can be brought?
- Which sample may be used, and which may be contributed?
- What handling does each restricted dataset require?

## Attribution and visibility observed before

In earlier GRP work (September 2026), contributions were auto-approved and became visible to
every user at once. One cross-account attribution question is still unresolved. Until
behaviour is checked in the sprint environment, use only permitted, non-sensitive samples, and
record the account and environment used for every submit (`outputs/contributions.jsonl` does
this).
