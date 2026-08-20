"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const sourcePath = process.argv[process.argv.length - 1];
if (!sourcePath) {
  throw new Error("Pass the production app.js path to this harness.");
}

const source = fs.readFileSync(sourcePath, "utf8");
const startMarker = "// CATALOG_UI_LOGIC_START";
const endMarker = "// CATALOG_UI_LOGIC_END";
const start = source.indexOf(startMarker);
const end = source.indexOf(endMarker);
assert.ok(start >= 0 && end > start, "Production catalog logic markers were not found.");

const logic = source.slice(start + startMarker.length, end);
const context = { console };
vm.createContext(context);
vm.runInContext(`${logic}\nthis.catalogTestApi = {
  isCatalogScan,
  catalogSources,
  catalogMetadataFields,
  visibleCatalogSources,
  setVisibleCatalogSelection,
};`, context);

const {
  isCatalogScan,
  catalogSources,
  catalogMetadataFields,
  visibleCatalogSources,
  setVisibleCatalogSelection,
} = context.catalogTestApi;

const scan = {
  source_kind: "catalog",
  metadata_headers: ["Country", "Research Group"],
  sources: [
    { id: "source-0001", source_id: "source-0001", speaker: "Pooled (no speaker)", metadata: { Country: "Ireland", "Research Group": "B" } },
    { id: "source-0002", source_id: "source-0002", speaker: "Speaker A", metadata: { Country: "Canada", "Research Group": "A" } },
    { id: "source-0003", source_id: "source-0003", speaker: "Speaker A", metadata: { Country: "Ireland", "Research Group": "A" } },
  ],
};

assert.strictEqual(isCatalogScan(scan), true);
assert.deepStrictEqual(Array.from(catalogMetadataFields(scan)), ["Country", "Research Group"]);
assert.deepStrictEqual(Array.from(catalogSources(scan), (item) => item.source_id), [
  "source-0001",
  "source-0002",
  "source-0003",
]);

const selected = new Set(["source-0001", "source-0002"]);
const visible = visibleCatalogSources(scan.sources, {
  filterField: "Country",
  filterText: "ire",
  sortField: "Research Group",
  sortDirection: "asc",
});
assert.deepStrictEqual(Array.from(visible, (item) => item.source_id), ["source-0003", "source-0001"]);
assert.deepStrictEqual(Array.from(selected), ["source-0001", "source-0002"], "filtering and sorting must not mutate selection");

const afterSelectVisible = setVisibleCatalogSelection(selected, visible, true);
assert.deepStrictEqual(Array.from(afterSelectVisible).sort(), ["source-0001", "source-0002", "source-0003"]);
const afterClearVisible = setVisibleCatalogSelection(afterSelectVisible, visible, false);
assert.deepStrictEqual(Array.from(afterClearVisible), ["source-0002"]);
assert.deepStrictEqual(Array.from(selected), ["source-0001", "source-0002"], "selection helpers return a new set");

console.log("catalog UI logic harness passed");
