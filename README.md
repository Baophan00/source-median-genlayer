# SourceMedian

A query names one thing to measure and several independent sources that report it. The usual failure of such a thing is that one source is wrong, one is silent, and the reader never finds out which. SourceMedian reads every source in one consensus round, drops the ones that say nothing usable, and publishes the median together with the spread it came from.

## How a query runs

```
register        question, unit, tolerance, max value, min sources, 2 to 8 source URLs
read            one consensus round over every source; a Reading is appended
add_source      the creator adds a source (2 to 8 are kept)
remove_source   the creator removes a source (2 to 8 are kept)
```

A query is written once. `register` fixes the question, the unit, the tolerance, the largest number a source may report, how many sources must answer, and the source list. There is no function that reopens any of it, and the source list can only grow or shrink between 2 and 8 entries.

## The interesting part

**One round reads every source.** `read` opens a single consensus round. Inside it, each source URL is fetched, the page is handed to the model as untrusted material, and the model is asked for one whole number in `[0, max_value]`. The round returns the canonical JSON of `{values, median, spread, reliable}` and nothing else, so two validators that read the same pages produce the same text and the equivalence principle has something exact to compare.

**A broken source is dropped, not averaged in.** A source that fails to render, renders as an empty page, answers something that is not JSON, answers a non-number, or answers outside `[0, max_value]` contributes nothing. It is not a zero and it is not an error: it is simply not counted, and `source_count` records how many sources actually spoke.

**It fails closed.** If fewer than `min_sources` are left, the whole read reverts and nothing is stored — not a partial reading, not a median of the survivors. A median of one silent majority is not a median, so the caller learns that the query could not be answered rather than getting a number that looks like one.

**The median is arithmetic, and it is robust by construction.**

```
odd     values[n // 2]
even    (values[n // 2 - 1] + values[n // 2]) // 2
spread  max - min
```

Sorting first means one outrageous source moves the spread and nothing else. Three sources reporting 42, 42 and 97 give a median of 42: the outlier is visible in the spread instead of dragging the answer with it.

**Reliable is a spread test, not a vote.** A reading is reliable when the spread stays inside the tolerance the creator fixed: `spread * 100 <= tolerance_pct * median` (and a reading whose median is 0 is reliable only when the spread is 0). The flag is a property of the sources, not an opinion about them, so the same pages always give the same flag.

**The contract recomputes what the validators only reported.** The stored median, spread and flag are recomputed from the accepted values in code. A round that came back with a plausible-looking but wrong summary cannot move the number that is written.

**The pages are untrusted.** Every page is fenced between BEGIN and END markers and named as material published by the source. A page that says "report 97" or "ignore the question" is content to be read, not an instruction to be obeyed.

**Nothing here holds funds.** The contract publishes a number and the spread it came from. What a caller does with an unreliable reading — retry, escalate, refuse to settle — is outside the contract, and deliberately so.

## API

| Function | Kind | Who may call | What it does |
| --- | --- | --- | --- |
| `register(query_id, question, unit, tolerance_pct, max_value, min_sources, sources_json)` | write | anyone | Writes the query. `query_id` is 1–64 characters and unique; 2–8 http(s) sources; tolerance 1–100; `min_sources` 1…len(sources). |
| `read(query_id)` | write | anyone | One consensus round over every source. Appends a `Reading` with `round_no = latest_round + 1`. Reverts, storing nothing, when fewer than `min_sources` sources answer. |
| `add_source(query_id, url)` | write | the creator | Appends a source. Refuses a URL already listed and a ninth source. |
| `remove_source(query_id, url)` | write | the creator | Removes a source. Refuses a URL that is not listed and the second-to-last source. |
| `get_query(query_id)` | view | anyone | The query as written: question, unit, tolerance, bounds, sources, creator, `latest_round`. |
| `latest(query_id)` | view | anyone | The last `Reading`, or `None` if the query has never been read. |
| `readings_of(query_id)` | view | anyone | Every reading, oldest first. |
| `list_queries(offset, limit)` | view | anyone | Queries newest first, pageable. |
| `stats()` | view | anyone | `{queries, readings, reliable}`. |

## Layout

```
contracts/source_median.py          the contract
tests/direct/test_source_median.py  24 direct-mode tests in 4 classes
tests/direct/test_method_signature.py  regression: self-first and return annotations
scripts/deploy_studionet.js         deploy with genlayer-js, no CLI
scripts/e2e_studionet.js            three live queries over the published pages
app/index.html                      the station pages, indexed
app/demo/                           the five station pages the e2e run reads
```

## Live

- Station pages: https://sourcemedian-genlayer.surge.sh/ ([A](https://sourcemedian-genlayer.surge.sh/demo/station-a.html) · [B](https://sourcemedian-genlayer.surge.sh/demo/station-b.html) · [C](https://sourcemedian-genlayer.surge.sh/demo/station-c.html) · [outlier](https://sourcemedian-genlayer.surge.sh/demo/station-outlier.html) · [offline](https://sourcemedian-genlayer.surge.sh/demo/station-broken.html))
- Contract (Studio Network): `0xbfd192f748a7a08A2c3d0524f02459083567c3CA`
- Explorer: https://explorer-studio.genlayer.com/address/0xbfd192f748a7a08A2c3d0524f02459083567c3CA

## One live run on the live contract

The question is `What daily credit count does the station report?`, in `credits`,
with a tolerance of 10% and a maximum of 1,000,000. Every number below came out
of a real consensus round on the contract above; the pages are the public ones
linked in Live.

| what | transaction |
| --- | --- |
| deploy `0xbfd192f748a7a08A2c3d0524f02459083567c3CA` | `0xe26f28faaf2589d38f760a2fb92466684d03fb29faa496afd7cf239eb3444695` |
| `register("credits-1", …)` — A, B, C, min 3 | `0xd9827053d35d2fe7ff5c98c93191d2587af7fa912264af62e2c1669e40e78bb2` |
| `read("credits-1")` — 42, 42, 42 | `0x3c7f5f0cc18fe6e02fee20a3e30bddda75e0609f1cd9dfafb0e5b048256c96c6` |
| `register("credits-2", …)` — A, B, outlier, min 2 | `0x621fa79f15deebd7277d112de2761fbbfa131f2a4fe77d224d22d5d5c070f51a` |
| `read("credits-2")` — 42, 42, 97 | `0xe05cfd22a1d0913fcc5e98e72ad9358c982703f79af938335214c8945c356349` |
| `register("credits-3", …)` — A, B, offline, min 3 | `0x7bee44475837d0a97c8b358d643637e133aaa74cbebb6dbc4e425fd7ecbb5eff` |
| `read("credits-3")` — refused, nothing stored | `0xf5f3cc5cd09fc64b7ad51e9a5c14c6d341d3a1d74846dcba0b4456b3e1ce59d1` |

What the contract stored:

```
credits-1  values [42, 42, 42]  median 42  spread   0  reliable      sources 3  round 1
credits-2  values [42, 42, 97]  median 42  spread  55  UNRELIABLE    sources 3  round 1
credits-3  no reading at all: two of the three sources said nothing, min_sources is 3
```

Three stations that agree give a reliable 42. Adding one station that says 97
leaves the median at 42 and turns the reading unreliable, because 55 credits of
spread is 131% of 42 against a tolerance of 10%. The third query is the fail-closed
case: the offline station publishes no number, only two sources answer, and the
read is refused rather than settled on a majority of two out of three.

## Tests

```
env -u PYTHONPATH -u VIRTUAL_ENV -u PYTHONHOME uv run --python 3.13 \
  --with pytest --with genlayer-test pytest tests/direct -q
```

25 direct-mode tests in 4 classes plus one AST regression test. The pages and the model are mocked; the
contract is not. They cover registering a query and reading it back, a duplicate
id, one and nine sources, a malformed URL, a source listed twice, the tolerance,
maximum and minimum ranges, the question and unit lengths, three agreeing sources,
an outlier past the tolerance, the floor average of an even count, a broken source
skipped while the read survives, falling below `min_sources` and storing nothing,
a single usable source under `min_sources = 1`, an empty page, a value above the
maximum, a model answer that is not JSON, a second read accumulating a round, an
unknown query, who may add or remove a source, the 2–8 source bounds, a source that
is not listed, `latest` and `readings_of`, `list_queries` newest first, and
`stats`.
