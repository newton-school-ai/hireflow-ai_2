/**
 * Smoke test for the frontend scaffold.
 *
 * Validates that the greet() function from main.js works correctly.
 * This ensures Vitest collects at least one test so 'npm run test'
 * exits with code 0 in CI.
 *
 * As the frontend grows, more meaningful component and integration
 * tests will be added alongside the UI code.
 */

import { describe, it, expect } from "vitest";
import { greet } from "./main.js";

describe("greet", () => {
  it("should return a welcome message with the given name", () => {
    expect(greet("Alice")).toBe("Welcome to HireFlow, Alice!");
  });

  it("should include the name in the output", () => {
    const result = greet("Bob");
    expect(result).toContain("Bob");
  });
});
