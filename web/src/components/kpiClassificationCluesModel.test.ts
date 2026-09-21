import assert from "node:assert/strict";
import test from "node:test";

import { hasActionableKpiClassificationClues } from "./kpiClassificationCluesModel.ts";

test("hides the whole KPI classification clue feature without actionable clues", () => {
  assert.equal(
    hasActionableKpiClassificationClues({ unclassified: 0, unregistered: 0, ambiguous: 0 }),
    false,
  );
  assert.equal(hasActionableKpiClassificationClues({ classified: 2, reserved: 3 }), false);
  assert.equal(hasActionableKpiClassificationClues({}), false);
  assert.equal(hasActionableKpiClassificationClues({ unclassified: 1 }), true);
  assert.equal(hasActionableKpiClassificationClues({ unregistered: 1 }), true);
  assert.equal(hasActionableKpiClassificationClues({ ambiguous: 1 }), true);
});
