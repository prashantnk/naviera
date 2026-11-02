// frontend/src/lib/validations/shipment.test.ts
import { describe, expect, it } from "vitest";
import * as z from "zod";
import { addPackageDimensionIssues } from "./shipment";

/** Runs the shared A-26 rule on a list of boxes and returns the issue paths. */
function issuePaths(packages: Array<{ length: number; breadth: number; height: number }>): string[] {
  const schema = z.array(z.any()).superRefine((value, ctx) => addPackageDimensionIssues(value, ctx));
  const result = schema.safeParse(packages);
  return result.success ? [] : result.error.issues.map((issue) => issue.path.join("."));
}

describe("addPackageDimensionIssues (A-26)", () => {
  it("accepts boxes with real dimensions", () => {
    expect(issuePaths([{ length: 10, breadth: 10, height: 5 }])).toEqual([]);
  });

  it("flags every zero or missing side, per box", () => {
    expect(
      issuePaths([
        { length: 10, breadth: 0, height: 5 },
        { length: 0, breadth: 0, height: Number.NaN },
      ]),
    ).toEqual([
      "packages.0.breadth",
      "packages.1.length",
      "packages.1.breadth",
      "packages.1.height",
    ]);
  });
});
