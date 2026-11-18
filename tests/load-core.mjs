// index.html에서 계산 로직(<script id="tally-core">)만 뽑아 화면 없이 실행한다.
import { readFileSync } from "node:fs";
import vm from "node:vm";

export const htmlPath = new URL("../index.html", import.meta.url);
export const html = readFileSync(htmlPath, "utf8");

export function loadCore() {
  const m = html.match(/<script id="tally-core">([\s\S]*?)<\/script>/);
  if (!m) throw new Error("index.html에 tally-core 스크립트가 없다");
  const context = vm.createContext({});
  vm.runInContext(m[1], context, { filename: "index.html#tally-core" });
  return context.SurveyTally;
}
