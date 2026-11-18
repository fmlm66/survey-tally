# 아침 뉴스 요약

정해 둔 주제에 관한 뉴스를 지정한 신문사·방송사의 RSS에서 골라, 매일 아침 짧은 요약 페이지로 만듭니다.

- 보는 곳: https://fmlm66.github.io/survey-tally/news/ (지난 요약도 같은 페이지 아래에 있습니다)
- 실행: GitHub Actions가 매일 06:40(한국 시각)에 돌립니다. GitHub 사정으로 몇 분~수십 분 늦을 수 있습니다. Actions 탭의 **news-digest daily** → **Run workflow**로 바로 돌릴 수도 있습니다.
- 외부 API·유료 서비스를 쓰지 않고, Python 표준 라이브러리만 씁니다.

## 주제·언론사 바꾸기

`config.json`을 고칩니다.

| 항목 | 뜻 |
| --- | --- |
| `topic` | 페이지 제목에 쓰는 주제 이름 |
| `keywords` | 이 중 하나라도 제목이나 요약문에 있으면 주제 기사로 봅니다. 제목에 있으면 3점, 요약문에만 있으면 1점 |
| `exclude_keywords` | 이 단어가 있는 기사는 뺍니다 |
| `window_hours` | 최근 몇 시간 안의 기사만 볼지(기본 24) |
| `max_articles` / `per_source_max` | 하루 최대 기사 수 / 한 언론사에서 최대 기사 수 |
| `sources` | 언론사 이름(`name`)과 RSS 주소 목록(`feeds`) |

영문 키워드(`AI` 등)는 영문 단어 속에 묻힌 경우(`MAIN`, `OpenAI`)는 세지 않습니다. `OpenAI`를 잡으려면 따로 적으세요.

## 고르는 방법

1. 최근 `window_hours` 안에 나온 기사만 봅니다(날짜가 없는 기사는 뺍니다).
2. 키워드 점수가 0이면 뺍니다.
3. 제목이 비슷한 기사는 한 소식으로 묶고 "같은 소식: 다른 언론사"로 적습니다.
4. 여러 언론사가 다룬 소식 → 점수 → 최신 순으로 놓습니다.

요약은 언론사가 RSS에 실어 주는 요약문의 앞 두 문장(최대 200자)이며, 기자 표기(`(서울=연합뉴스) 홍길동 기자 =`) 등은 걷어 냅니다. 기사 본문은 가져오지 않으니 전체 내용은 원문 링크에서 보세요.

## 직접 돌리기·시험

```bash
cd news-digest
```

```bash
python -m newsdigest --check-feeds
```

```bash
python -m newsdigest --out ../news
```

```bash
python -m unittest -v
```

`--check-feeds`는 각 RSS 주소가 열리는지, 기사와 날짜가 읽히는지 표로 보여 줍니다. PR마다 CI에서도 돌려 작업 요약(Summary)에 표를 남깁니다.
