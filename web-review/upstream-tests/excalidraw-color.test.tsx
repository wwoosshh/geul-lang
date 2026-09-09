// Copied unchanged into each pinned upstream revision by check-upstream-color.
// Scenario expectations are hand specified, not produced by the color parser,
// the DOM, the hook state, or the geul IR under test.
import React from "react";
import { writeFileSync } from "node:fs";
import { Excalidraw } from "../index";
import { fireEvent, render, waitFor, toggleMenu } from "./test-utils";
import spec from "./geul-color-scenarios.json";

const revision = process.env.GEUL_REVISION;
if (revision !== "before" && revision !== "after") throw new Error("Missing revision");
if (spec.schema !== "web-color-scenarios-1") throw new Error("Unexpected scenario schema");
const observations: unknown[] = [];
const originalResizeObserver = Object.getOwnPropertyDescriptor(globalThis, "ResizeObserver");

beforeEach(() => {
  localStorage.clear();
  // Same no-op layout observer as the original colorInput.test.tsx. It does not
  // establish pixel placement, animation timing, or assistive-technology output.
  Object.defineProperty(globalThis, "ResizeObserver", {
    configurable: true, writable: true,
    value: class { observe() {} unobserve() {} disconnect() {} },
  });
});
afterAll(() => {
  if (originalResizeObserver) Object.defineProperty(globalThis, "ResizeObserver", originalResizeObserver);
  else Reflect.deleteProperty(globalThis, "ResizeObserver");
  if (!process.env.GEUL_OBSERVATIONS) throw new Error("Missing output path");
  writeFileSync(process.env.GEUL_OBSERVATIONS, JSON.stringify({
    schema: "geul-upstream-color-observations-1", revision, observations,
  }, null, 2) + "\n", { flag: "wx" });
});

for (const scenario of spec.scenarios) {
  it(`records original color input: ${scenario.id}`, async () => {
    const { container } = await render(<Excalidraw langCode="en"
      initialData={{ appState: { viewBackgroundColor: spec.initialColor } }} />);
    // Original menu and picker click handlers, without assigning open-menu or
    // error state through the test API.
    toggleMenu(container);
    const button = container.querySelector('[data-openpopup="canvasBackground"]');
    expect(button).toBeTruthy();
    fireEvent.click(button!);
    await waitFor(() => expect(container.querySelectorAll(".color-picker-input")).toHaveLength(1));
    const input = container.querySelector(".color-picker-input") as HTMLInputElement;

    async function capture(phase: string, action: unknown, display: string, saved: string, error: string | null) {
      const message = revision === "after" && error !== null
        ? spec.messages[error as keyof typeof spec.messages] : null;
      if (error !== null && !Object.hasOwn(spec.messages, error)) throw new Error("Unknown expected error");
      const expected = {
        display, saved,
        ariaPresent: revision === "after",
        ariaInvalid: revision === "after" ? String(message !== null) : null,
        errorText: message, errorRole: message !== null ? "alert" : null,
        errorCount: message !== null ? 1 : 0, hasErrorClass: message !== null,
      };
      const read = () => {
        const errors = [...container.querySelectorAll(".color-picker__error-message")];
        return {
          display: input.value, saved: window.h.state.viewBackgroundColor,
          ariaPresent: input.hasAttribute("aria-invalid"),
          ariaInvalid: input.getAttribute("aria-invalid"),
          errorText: errors[0]?.textContent ?? null,
          errorRole: errors[0]?.getAttribute("role") ?? null,
          errorCount: errors.length,
          hasErrorClass: input.closest(".color-picker__input-label")?.classList.contains("has-error") ?? false,
        };
      };
      await waitFor(() => expect(read()).toEqual(expected));
      observations.push({ id: scenario.id, phase, action, actual: read() });
    }

    await capture("initial", { kind: "open-menu-and-picker" }, "ffffff", spec.initialColor, null);
    for (const step of scenario.steps) {
      const action = "change" in step ? { kind: "change", value: step.change } : { kind: "blur" };
      if ("change" in step) fireEvent.change(input, { target: { value: step.change } });
      else fireEvent.blur(input);
      const display = revision === "before" && "beforeDisplay" in step ? step.beforeDisplay! : step.display;
      await capture(step.id, action, display, step.saved, step.error);
    }
  }, 15_000);
}
