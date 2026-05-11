# Session Handoff

다른 서버/시점의 claude code 인스턴스가 컨텍스트를 빠르게 복원하기 위한 핸드오프 노트.
**핵심 영구 규약은 갱신 시 신중하게**, 활성 작업 섹션은 자유롭게 갱신.

---

## 현재 활성 작업 (2026-05-11 기준)

**완료 상태**: T/NT 토글 정정 + Kanana sibling-variant 추가 + parser 정정 + 옵션 B (4쌍 ablation) 적용 완료.

**최종 모델 구성 (29개)**:
- 동일 모델 enable_thinking 토글 4쌍: Qwen3.5-4B/27B, gpt-oss-20B/120B
- Kanana sibling-variant pair (별도): `kanana-2-30b-a3b-instruct-2601` (NT-only) ↔ `kanana-2-30b-a3b-thinking-2601` (always-thinking)
- baseline `kanana-2-30b-a3b-instruct` 별개로 유지 (구 baseline)

**최근 정정 이력 (2026-05-08 ~ 2026-05-11)**:
- gpt-oss-20B/120B T/NT 토글 정정 재실험 (KR/EN/MT)
- kanana-2-30b-a3b-instruct-2601 신규 sibling-variant 추가 + parser 정정 (`hermes` → `functionary_v3_llama_31`) 후 재실험
- kanana-2-30b-a3b-thinking-2601 (Kanana-2-Think) 출처 미상 데이터 → 단일 entry 재실험으로 일관화
- main.tex 옵션 B 적용: 5쌍 → 4쌍 thinking ablation, Kanana sibling pair는 별도 보고
- comparison/figure 자동 재생성, 자동 표 생성 스크립트 model_id 정규화 fix
- gpt-oss-120b KR T 누락 6건 보충 + gpt-oss-20b KR checkpoint dedup (각각 _backup으로 출처 archive)

**환경 셋업** (불변):
- 모든 캐시(`HF_HOME`, `VLLM_CACHE_ROOT`, `flashinfer`, `pip` 등)를 Lustre `/home/work/kftc_model/.cache/`로 redirect (`.bashrc` + `run_rerun_all.sh` 영구 설정)
- pip 패키지 user-base는 `/home/work/kftc_model/.local` (PYTHONUSERBASE)
- vllm 0.20.1 + flashinfer 0.6.8.post1

**런처**: `_paper/_experiments/scripts/run_rerun_all.sh <group> <gpu> <port>` (KR→EN→MT 순차).
- 그룹: `gpt_oss_20b`, `gpt_oss_120b`, `kanana_inst_2601`, `kanana_think` (each `RERUN_*` group)
- vLLM 통신 segfault 회피: `BENCH_CONCURRENCY=1`로 단일 스레드 권장 (Kanana-2-Think EN에서 concur=8/4 시 segfault 재발 확인)

이전 실험 (Round 1~7, 5/3 baseline 등) 의 누적 commit 이력은 `git log` 참조.

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
5. **벤치마크 정합성**: 모든 정수 코드 → HOFINET 유효 값만. 위 §2 매핑 표 + `_datasets/HOFINET.MD` 참조.
6. **commit 메시지**: `Co-Authored-By: Claude` 라인 추가 금지 (사용자 명시 선호).
7. **submodule push 순서**: `_paper` repo → main repo submodule pointer 갱신 → 양쪽 push.

---

## 갱신 정책

- 영구 규약 변경 시 → 이 파일과 `CLAUDE.md` 동시 갱신
- 진행 중 작업 변경 시 → 이 파일의 "현재 활성 작업" 섹션만 갱신
- 결정 내역 → commit 메시지 본문에 명확히 기록 (`git log`로 복원)
