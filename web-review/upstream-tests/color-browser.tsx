// Browser test host. Original Excalidraw/ColorInput/React/CSS are unmodified.
import React, { useRef } from "react";
import { createRoot } from "react-dom/client";
import { Excalidraw } from "./packages/excalidraw";
import type { AppState } from "./packages/excalidraw/types";

function Harness() {
  const output = useRef<HTMLOutputElement | null>(null);
  const status = useRef<HTMLParagraphElement | null>(null);
  const record = (_: unknown, state: AppState) => {
    if (output.current) output.current.textContent = JSON.stringify({
      viewBackgroundColor: state.viewBackgroundColor,
      width: state.width, height: state.height,
    });
  };
  return <>
    <header>
      <p className="eyebrow">글 · 원본 앱 실행 검증</p>
      <h1>색상 입력 관찰</h1>
      <p>메뉴에서 Canvas background를 열어 원본 입력창을 조작합니다.</p>
      <p className="revision">원본 커밋 <code id="source-commit">{__GEUL_COMMIT__}</code></p>
    </header>
    <main>
      <div className="original-app"><Excalidraw
        initialData={{ appState: { viewBackgroundColor: "#ffffff" } }}
        langCode="en" onChange={record}
        onInitialize={() => { if (status.current) status.current.textContent = "원본 앱 초기화 완료"; }}
      /></div>
      <aside>
        <p ref={status} role="status">원본 앱 초기화 중</p>
        <h2>앱이 전달한 관찰값</h2>
        <output id="color-observed-state" ref={output} />
        <p>원본 onChange 콜백의 배경색입니다. 입력창에 남아 있는 문자열과 구분합니다.</p>
        <p>이 화면은 실제 CSS·React·브라우저로 지정한 경로를 검사합니다. 모든 동작의 검증 완료를 뜻하지 않습니다.</p>
      </aside>
    </main>
  </>;
}
createRoot(document.getElementById("root")!).render(<Harness />);
