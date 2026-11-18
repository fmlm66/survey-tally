// index.html이 외부로 데이터를 보내거나 저장하지 않는지 정적으로 확인한다.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, statSync } from "node:fs";
import { html } from "./load-core.mjs";

const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];

test("스크립트는 모두 인라인이고 계산과 화면이 나뉘어 있다", () => {
  assert.deepEqual(scripts.map((m) => m[1].trim()), ['id="tally-core"', 'id="tally-ui"']);
  const core = scripts[0][2];
  assert.doesNotMatch(core, /\b(document|window|navigator)\b/, "계산 로직은 DOM에 기대지 않는다");
});

test("외부 주소를 불러오지 않는다", () => {
  const markup = html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, "");
  assert.doesNotMatch(markup, /<[a-z][^>]*\s(src|href|action|poster|data|srcset)\s*=/i, "src/href 등 리소스 속성 없음");
  assert.doesNotMatch(html, /https?:\/\/|\/\/[a-z0-9.-]+\.[a-z]{2,}/i, "외부 주소 없음");
  assert.doesNotMatch(html, /@import|@font-face|url\(/i, "외부 글꼴·스타일 없음");
  assert.doesNotMatch(html, /<(link|iframe|object|embed|img|form)\b/i);
});

test("네트워크 호출·저장소 API를 쓰지 않는다", () => {
  const code = scripts.map((m) => m[2]).join("\n");
  for (const api of [
    "fetch", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource",
    "localStorage", "sessionStorage", "indexedDB", "cookie", "caches",
    "serviceWorker", "postMessage", "eval", "Function(", "innerHTML",
  ]) {
    assert.ok(!code.includes(api), `${api} 사용 안 함`);
  }
});

test("CSP가 외부 연결을 막는다", () => {
  const m = html.match(/http-equiv="Content-Security-Policy" content="([^"]+)"/);
  assert.ok(m, "CSP 메타 태그 있음");
  assert.match(m[1], /default-src 'none'/);
  assert.match(m[1], /form-action 'none'/);
});

test("입력칸은 자동완성·맞춤법 검사를 끈다", () => {
  const ta = html.match(/<textarea\b[^>]*>/)[0];
  assert.match(ta, /autocomplete="off"/);
  assert.match(ta, /spellcheck="false"/);
});

test("결과 표 머리글", () => {
  assert.ok(html.includes('["문항", "유효 응답", "평균", "빈 응답", "제외"]'));
});

test(".nojekyll은 저장소 맨 위의 빈 파일이다", () => {
  const p = new URL("../.nojekyll", import.meta.url);
  assert.equal(statSync(p).size, 0);
  assert.equal(readFileSync(p, "utf8"), "");
});
