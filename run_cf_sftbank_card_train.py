"""SFTBank-style CF structure-lineage training + TEST (repo-root entry).

The Count Frequency port of the queenbee-SFTbank card-training pipeline
(``--lineage structure`` mode): a verified single-structure lineage duels
frozen phase programs on a tier-balanced CF case envelope, confirms wins on
fresh review cases, then runs a one-shot read-only TEST with reference
baseline arms.  The default information goal is ``sink``: only the final
agent's submitted frequency table is scored.

Offline smoke (no API calls, deterministic operators):

    python run_cf_sftbank_card_train.py --rounds 4 --envelope-cases 3

Real campaign, matching the SFTBank invocation shape:

    CF_SFT_PAID_CALLS_APPROVED=yes OPENAI_API_KEY=... \
    python run_cf_sftbank_card_train.py \
        --llm openai --lineage structure --rounds 16 --envelope-cases 3
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent / "exp-graph"
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from exp_graph.sft_lineage.card_train_cf import main  # noqa: E402

if __name__ == "__main__":
    main()
