// Browser fixture only: the imported app, React, CSS, fonts and observers are real.
import React, { useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Excalidraw, convertToExcalidrawElements } from "./packages/excalidraw";
import type { AppState, ExcalidrawImperativeAPI, ExcalidrawProps } from "./packages/excalidraw/types";

const initialData = { elements: convertToExcalidrawElements([
  { type: "rectangle", x: 110, y: 180, width: 120, height: 90, backgroundColor: "#a5d8ff", fillStyle: "solid" },
]) };
const uiOptions: Record<string, ExcalidrawProps["ui"]> = {
  default: undefined,
  "scroll-only": { enabled: { scrollBackToContent: true } },
  disabled: false,
};

function Harness() {
  const api = useRef<ExcalidrawImperativeAPI | null>(null);
  const output = useRef<HTMLPreElement | null>(null);
  const [viewMode, setViewMode] = useState(true);
  const [ui, setUI] = useState("scroll-only");
  const [ready, setReady] = useState(false);
  const record = (_: unknown, state: AppState) => {
    if (output.current) output.current.textContent = JSON.stringify({
      viewModeEnabled: state.viewModeEnabled, scrolledOutside: state.scrolledOutside,
      openMenu: state.openMenu, openSidebar: state.openSidebar,
      scrollX: state.scrollX, scrollY: state.scrollY,
      width: state.width, height: state.height,
    }, null, 2);
  };
  return <>
    <header className="harness-header">
      <h1>원본 앱 · 복귀 버튼 검증</h1>
      <p>고정 원본: <code>{__GEUL_COMMIT__}</code></p>
      <p>실제 React·CSS·브라우저. 호스트 API로 만든 초기 조건과 사용자 클릭 결과를 구분합니다.</p>
    </header>
    <div className="harness-controls">
      <label>보기 모드<select aria-label="보기 모드" value={String(viewMode)} onChange={event => setViewMode(event.target.value === "true")}>
        <option value="true">켜짐</option><option value="false">꺼짐</option>
      </select></label>
      <label>기본 UI<select aria-label="기본 UI" value={ui} onChange={event => setUI(event.target.value)}>
        <option value="scroll-only">복귀 버튼만</option><option value="default">전체 기본 UI</option><option value="disabled">모두 끔</option>
      </select></label>
      <button disabled={!ready} onClick={() => api.current?.updateScene({ appState: { scrollX: -10000, scrollY: -10000 } })}>멀리 이동 · 호스트 API</button>
    </div>
    <main className="harness-body">
      <div className="harness-editor"><Excalidraw
        initialData={initialData} viewModeEnabled={viewMode} ui={uiOptions[ui]}
        onExcalidrawAPI={value => { api.current = value; }}
        onInitialize={() => setReady(true)} onChange={record} langCode="en"
      /></div>
      <aside className="harness-evidence">
        <p role="status">{ready ? "원본 앱 초기화 완료" : "원본 앱 초기화 중"}</p>
        <p>관찰된 원본 AppState</p><pre id="observed-state" ref={output} />
        <p>이 화면은 390 × 650 크기의 앱을 담습니다. 복귀 버튼의 생성·배치·가림과 클릭 후 상태를 확인하는 제한된 실행 사례입니다.</p>
      </aside>
    </main>
  </>;
}
createRoot(document.getElementById("root")!).render(<Harness />);
