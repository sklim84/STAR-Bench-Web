# Session Handoff

다른 서버의 claude code 인스턴스가 이 repo에서 첫 세션을 시작할 때 자동으로 참조하는 핸드오프 노트.
세션 종료 시 갱신, 시작 시 읽기.

---

## 현재 활성 작업 (2026-04-29 17:30 기준)

**메인 작업**: AML-Bench Round 1 재실험 (NeurIPS 2026 E&D 마감 5/6)

**상태**:
- HOFINET 정합성 정정 완료 (코드 + 벤치마크 케이스)
- 시스템 프롬프트 간소화 완료 (Native FC + 23-tool 중복 제거)
- v6 master 진행 중 (KR phase, Group A [2/11], Group B [4/11])

**인증 commit**:
- `_paper` (submodule): `4477e49`
- Main repo: `5ae7758`

---

## 다른 서버에서 진행할 작업 (분리됨)

이 서버(GPU 0/1)는 **non-TP=2, non-thinking 변형**만 실험 중. 다른 서버에서 진행 권장:

### A. TP=2 그룹 (70B+ 3 모델 × KR/EN/MT)

```bash
git pull --recurse-submodules
bash _paper/_experiments/scripts/run_benchmark.sh --gpu 0,1 --port 11434 --group TP2 --mode kr
bash _paper/_experiments/scripts/run_benchmark.sh --gpu 0,1 --port 11434 --group TP2 --mode en
bash _paper/_experiments/scripts/run_benchmark.sh --gpu 0,1 --port 11434 --group TP2 --mode mt
```

대상 모델:
1. `meta-llama/Llama-3.3-70B-Instruct`
2. `Salesforce/Llama-xLAM-2-70b-fc-r`
3. `skt/A.X-4.0` (72B)

각 모델 약 5~10시간, 총 ~45~90시간 (KR/EN/MT 합산).

### B. thinking ablation (9 모델 × think=True × KR/EN/MT)

별도 추후 진행. 모델 목록:
- Qwen3.5-0.8B/2B/4B/9B/27B (think=True)
- Qwen3-4B-Thinking-2507 (think=True)
- Qwen3-30B-A3B-Thinking-2507 (think=True)
- kakaocorp/kanana-2-30b-a3b-thinking-2601 (think=True)
- openai/gpt-oss-20b (think=True)

`benchmark.py` MODELS 리스트에 각 모델의 think=True 항목이 정의돼 있음. `--models <name>` 만 주면 think+nothink 두 변형 모두 실행되므로, thinking-only 실행을 위해서는 환경변수 `BENCH_ONLY_THINK=1` 사용 (별도 구현 예정).

---

## 핵심 영구 규약 (이 repo 작업 시 반드시 준수)

1. **용어**: `single-turn` / `multi-turn` (영어), `싱글턴` / `멀티턴` (한국어). `singleton` 금지 (design pattern 제외).
2. **HOFINET 공식 매핑**:
   - fraud_type: 1=Sudden Change, 2=New Counterparty, 3=Split, 4=Concurrent Multiple, 5=Same-Day Withdrawal, 7=Late-Night Bulk (코드 6 unused)
   - media_type: 1=PC Banking, 2=Internet Banking, 3=Phone, 4=Mobile Phone, 5=Per-transaction, 6=Other, 7=Bulk Transfer
   - fund_type: 0=General, 1=Salary, 3=Other, 4=Inter-bank Auto Transfer
   - time_slot: 0/3/6/9/12/15/18/21만 유효 (3시간 단위)
   - sender_bank 50개 / receiver_bank 54개 (`_datasets/HOFINET.MD` §6.5 참조)
3. **Native FC 모드 사용**: vLLM tool-call-parser + API tools 필드. Prompting mode 미사용.
4. **시스템 프롬프트**: 도구 정의 중복 금지. `Tool definitions are provided via the API tools field` 문구로 대체.
5. **벤치마크 정합성**: 모든 정수 코드 → HOFINET 유효 값만. `_paper/_experiments/WORK_LOG.md` 매핑 표 참조.
6. **commit 메시지**: `Co-Authored-By: Claude` 라인 추가 금지 (사용자 명시 선호).
7. **submodule push 순서**: `_paper` repo → main repo submodule pointer 갱신 → 양쪽 push.

---

## 컨텍스트 복원 시작 메시지 예시

```
이 repo의 CLAUDE.md, .claude/SESSION_HANDOFF.md, _paper/_experiments/WORK_LOG.md를
순서대로 읽고 컨텍스트를 복원해줘.

현재 다른 서버에서 v6 master가 KR phase 실행 중 (GPU 0/1, non-TP2 + non-thinking).
나는 이 서버에서 [TP=2 / thinking ablation / 다른 작업]을 진행할 예정이야.
```

---

## 갱신 정책

- 영구 규약 변경 시 → 이 파일과 `CLAUDE.md` 동시 갱신
- 진행 중 작업 변경 시 → 이 파일의 "현재 활성 작업" 섹션만 갱신
- 결정 내역 → `_paper/_experiments/WORK_LOG.md`에 시간 역순 누적
