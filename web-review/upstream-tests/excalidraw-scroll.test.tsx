// Copied unchanged into the pinned upstream test tree by check-upstream.mjs.
// This is a jsdom integration oracle. It does not assert pixel visibility.
import React from "react";
import { writeFileSync } from "node:fs";
import { Excalidraw } from "../index";
import type { ExcalidrawProps } from "../types";
import { API } from "./helpers/api";
import {
  act, fireEvent, GlobalTestState, mockBoundingClientRect, render,
  restoreOriginalGetBoundingClientRect, waitFor,
} from "./test-utils";

const { h } = window;
const observations: unknown[] = [];
const cases: { id: string; ui: ExcalidrawProps["ui"] }[] = [
  { id: "default", ui: undefined },
  { id: "scroll-only", ui: { enabled: { scrollBackToContent: true } } },
  { id: "disabled", ui: false },
  { id: "omitted", ui: { enabled: { zoom: true } } },
];

beforeEach(() => {
  localStorage.clear();
  mockBoundingClientRect({ width: 390, height: 844 });
});
afterEach(() => restoreOriginalGetBoundingClientRect());
afterAll(() => {
  if (!process.env.GEUL_OBSERVATIONS) throw new Error("Missing output path");
  writeFileSync(process.env.GEUL_OBSERVATIONS, JSON.stringify({
    schema: "geul-upstream-observations-1",
    revision: process.env.GEUL_REVISION,
    observations,
  }, null, 2) + "\n", { flag: "wx" });
});

function capture(id: string, phase: string) {
  const buttons = [...GlobalTestState.renderResult.container.querySelectorAll(
    "button.scroll-back-to-content",
  )];
  expect(buttons.length).toBeLessThanOrEqual(1);
  const result = {
    id, phase,
    input: {
      appState: { $record: {
        viewModeEnabled: h.state.viewModeEnabled,
        scrolledOutside: h.state.scrolledOutside,
        openMenu: h.state.openMenu,
        openSidebar: h.state.openSidebar === null ? null : { $record: { name: h.state.openSidebar.name } },
      } },
      defaultUIEnabled: h.app.isDefaultUIEnabled(),
      scrollBackToContentUIEnabled: h.app.isUIControlEnabled("scrollBackToContent"),
    },
    formFactor: h.app.editorInterface.formFactor,
    scroll: { x: h.state.scrollX, y: h.state.scrollY },
    buttonCount: buttons.length,
    buttonHtml: buttons.map(button => button.outerHTML),
    parentClasses: buttons.map(button => button.parentElement?.className),
  };
  expect(result.formFactor).toBe("phone");
  observations.push(result);
  return buttons;
}

for (const entry of cases) for (const viewModeEnabled of [false, true]) {
  const id = `${entry.id}/view-${viewModeEnabled}`;
  it(`records scroll DOM and click behavior: ${id}`, async () => {
    await render(<Excalidraw
      ui={entry.ui}
      viewModeEnabled={viewModeEnabled}
      UIOptions={{ getFormFactor: () => "phone" }}
      initialData={{ elements: [API.createElement({
        type: "rectangle", x: 10, y: 10, width: 50, height: 50,
      })] }}
    />);
    // jsdom does not drive browser layout/ResizeObserver; the window resize
    // listener exists only in edit mode. Invoke the original layout refresh as the
    // upstream withExcalidrawDimensions helper does, without assigning formFactor.
    act(() => { h.app.refreshEditorInterface(); h.app.refresh(); });
    await waitFor(() => expect(h.app.editorInterface.formFactor).toBe("phone"));
    expect(h.state.viewModeEnabled).toBe(viewModeEnabled);
    expect(h.state.scrolledOutside).toBe(false);
    capture(id, "initial");

    // Exercise the original native wheel handler; do not assign scrolledOutside.
    fireEvent.wheel(GlobalTestState.interactiveCanvas, { deltaX: 10_000, deltaY: 10_000 });
    await waitFor(() => expect(h.state.scrolledOutside).toBe(true));
    const buttons = capture(id, "wheel-away");
    if (buttons.length) {
      fireEvent.click(buttons[0]);
      await waitFor(() => expect(h.state.scrolledOutside).toBe(false));
      expect(capture(id, "click-back")).toHaveLength(0);
      fireEvent.wheel(GlobalTestState.interactiveCanvas, { deltaX: 10_000, deltaY: 10_000 });
      await waitFor(() => expect(h.state.scrolledOutside).toBe(true));
    }

    // These are explicitly test-API-injected states, not user reachability proof.
    act(() => h.app.setState({ openMenu: "canvas" }));
    await waitFor(() => expect(h.state.openMenu).toBe("canvas"));
    capture(id, "injected-menu");
    act(() => h.app.setState({ openMenu: null }));
    await waitFor(() => expect(h.state.openMenu).toBe(null));
    capture(id, "closed-menu");
    act(() => h.app.setState({ openSidebar: { name: "library" } }));
    await waitFor(() => expect(h.state.openSidebar?.name).toBe("library"));
    capture(id, "injected-sidebar");
    act(() => h.app.setState({ openSidebar: null }));
    await waitFor(() => expect(h.state.openSidebar).toBe(null));
    capture(id, "closed-sidebar");
  }, 15_000);
}
