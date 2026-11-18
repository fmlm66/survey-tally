import { test } from "node:test";
import assert from "node:assert/strict";
import { loadCore } from "./load-core.mjs";

const T = loadCore();

// vm 안에서 만든 객체는 프로토타입이 달라 deepStrictEqual이 어긋나므로 JSON으로 옮긴다.
const plain = (v) => JSON.parse(JSON.stringify(v));
const tally = (text) => plain(T.tally(text));
const byName = (text) => Object.fromEntries(tally(text).questions.map((q) => [q.name, q]));

test("칸 판정: 1~5만 유효, 빈칸·공백은 빈 응답, 나머지는 제외", () => {
  for (const v of ["1", "2", "3", "4", "5", " 3 ", "\t4", "5 ", "　2"]) {
    assert.equal(T.classifyCell(v), "valid", JSON.stringify(v));
  }
  for (const v of ["", " ", "   ", " ", "　", undefined, null]) {
    assert.equal(T.classifyCell(v), "blank", JSON.stringify(v));
  }
  for (const v of ["0", "6", "10", "1.0", "3.5", "-1", "+3", "3점", "a", "1 2", "１", "05", "-"]) {
    assert.equal(T.classifyCell(v), "excluded", JSON.stringify(v));
  }
});

test("평균: 소수 셋째 자리에서 반올림해 둘째 자리까지, 유효 0이면 -", () => {
  assert.equal(T.formatAverage(0, 0), "-");
  assert.equal(T.formatAverage(5, 2), "2.50");
  assert.equal(T.formatAverage(3, 1), "3.00");
  assert.equal(T.formatAverage(4, 3), "1.33"); // 1.3333…
  assert.equal(T.formatAverage(5, 3), "1.67"); // 1.6666…
  assert.equal(T.formatAverage(201, 200), "1.01"); // 1.005 → 올림
  assert.equal(T.formatAverage(1001, 200), "5.01"); // 5.005 → 올림
  assert.equal(T.formatAverage(535, 200), "2.68"); // 2.675: 부동소수점 toFixed는 2.67
  assert.equal(T.formatAverage(1999, 1000), "2.00"); // 1.999 → 2.00
  assert.equal(T.formatAverage(1994, 1000), "1.99"); // 1.994 → 1.99
});

test("기본 집계: 첫 열은 집계하지 않고 문항별 결과를 낸다", () => {
  const text = [
    "응답번호\t만족도\t추천 의향",
    "1\t5\t4",
    "2\t3\t",
    "3\t\t6",
    "4\t4\t2",
  ].join("\r\n") + "\r\n";
  const r = tally(text);
  assert.equal(r.hasHeader, true);
  assert.equal(r.responses, 4);
  assert.deepEqual(r.questions, [
    { name: "만족도", valid: 3, average: "4.00", blank: 1, excluded: 0 },
    { name: "추천 의향", valid: 2, average: "3.00", blank: 1, excluded: 1 },
  ]);
});

test("칸이 모자란 줄은 모자란 칸을 빈 응답으로 센다", () => {
  const q = byName("번호\tA\tB\tC\n1\t5\n2\n3\t1\t2\t3\n");
  assert.deepEqual(q.A, { name: "A", valid: 2, average: "3.00", blank: 1, excluded: 0 });
  assert.deepEqual(q.B, { name: "B", valid: 1, average: "2.00", blank: 2, excluded: 0 });
  assert.deepEqual(q.C, { name: "C", valid: 1, average: "3.00", blank: 2, excluded: 0 });
});

test("중간의 빈 줄은 모든 문항이 빈 응답인 줄, 끝의 빈 줄은 무시", () => {
  const r = tally("번호\tA\n1\t2\n\n3\t4\n\n\n");
  assert.equal(r.responses, 3);
  assert.deepEqual(r.questions[0], { name: "A", valid: 2, average: "3.00", blank: 1, excluded: 0 });
});

test("칸이 머리글보다 많은 줄은 넘치는 칸을 무시한다", () => {
  const r = tally("번호\tA\n1\t3\t9\t9");
  assert.equal(r.questions.length, 1);
  assert.deepEqual(r.questions[0], { name: "A", valid: 1, average: "3.00", blank: 0, excluded: 0 });
});

test("유효 응답이 없으면 평균은 -", () => {
  const r = tally("번호\tA\n1\t\n2\tx\n");
  assert.deepEqual(r.questions[0], { name: "A", valid: 0, average: "-", blank: 1, excluded: 1 });
});

test("응답번호 열 값은 판정에 쓰이지 않는다", () => {
  const r = tally("번호\tA\nx\t1\n\t2\n");
  assert.deepEqual(r.questions[0], { name: "A", valid: 2, average: "1.50", blank: 0, excluded: 0 });
});

test("줄 끝: CRLF, LF, CR 모두 처리", () => {
  for (const nl of ["\r\n", "\n", "\r"]) {
    const r = tally(["번호\tA", "1\t1", "2\t4"].join(nl) + nl);
    assert.equal(r.responses, 2, JSON.stringify(nl));
    assert.equal(r.questions[0].average, "2.50");
  }
});

test("엑셀 따옴표 칸: 줄바꿈·탭·따옴표를 품어도 한 칸으로 읽는다", () => {
  const text = '번호\t의견\t점수\n1\t"좋아요\n정말"\t5\n2\t"탭\t있음 ""인용"""\t4\n3\t"\t3\n';
  assert.deepEqual(plain(T.parseTSV(text)), [
    ["번호", "의견", "점수"],
    ["1", "좋아요\n정말", "5"],
    ["2", '탭\t있음 "인용"', "4"],
    ["3", '"', "3"], // 닫는 따옴표가 없으면 글자 그대로
  ]);
  const q = byName(text);
  assert.deepEqual(q["점수"], { name: "점수", valid: 3, average: "4.00", blank: 0, excluded: 0 });
  assert.deepEqual(q["의견"], { name: "의견", valid: 0, average: "-", blank: 0, excluded: 3 });
});

test('따옴표로 감싼 숫자 "3"은 3으로 본다', () => {
  assert.deepEqual(tally('번호\tA\n1\t"3"\n').questions[0].valid, 1);
});

test("머리글 이름: 앞뒤 공백 제거, 비면 열 번호", () => {
  const r = tally(" 번호 \t 만족도 \t\t  \n1\t1\t2\t3\n");
  assert.deepEqual(r.questions.map((q) => q.name), ["만족도", "열 3", "열 4"]);
});

test("빈 입력·머리글만·문항 없는 입력", () => {
  assert.deepEqual(tally(""), { hasHeader: false, responses: 0, questions: [] });
  assert.deepEqual(tally("\n\n"), { hasHeader: false, responses: 0, questions: [] });
  assert.deepEqual(tally("번호\n1\n2"), { hasHeader: true, responses: 2, questions: [] });
  const onlyHeader = tally("번호\tA\tB\r\n");
  assert.equal(onlyHeader.responses, 0);
  assert.deepEqual(onlyHeader.questions[0], { name: "A", valid: 0, average: "-", blank: 0, excluded: 0 });
});

test("BOM이 붙어 있어도 머리글을 읽는다", () => {
  assert.equal(tally("﻿번호\tA\n1\t2").questions[0].name, "A");
});

test("유효+빈+제외 = 응답 수 (모든 문항)", () => {
  const rows = ["번호\tA\tB\tC"];
  const vals = ["1", "5", " ", "", "x", "3", "6", " 2 "];
  for (let i = 0; i < 40; i++) {
    const n = i % 4; // 칸 수를 0~3개로 바꿔 모자란 줄도 섞는다
    const cells = [String(i + 1)];
    for (let k = 0; k < n; k++) cells.push(vals[(i * 3 + k) % vals.length]);
    rows.push(cells.join("\t"));
  }
  const r = tally(rows.join("\n"));
  assert.equal(r.responses, 40);
  for (const q of r.questions) assert.equal(q.valid + q.blank + q.excluded, 40, q.name);
});
