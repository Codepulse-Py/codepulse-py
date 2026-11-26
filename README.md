# codepulse-py
Real-time misconception detection and adaptive interention for introductory Python, fusing keystroke behviour and AST structure with a fine-tuned Qwen2.5-Coer-7B (SLIIT SE4012 final-year research).


## Layout

| Path | Purpose |
|---|---|
| `data/` | Raw ProgSnap2 datasets (`data/raw/`, git-ignored), labels, synthetic snippets |
| `detectors/` | Behaviour-state labeller and AST misconception detectors |
| `features/` | Sliding-window feature extraction |
| `models/` | Baselines, fine-tuning and serving (`models/serving/`) |
| `backend/` | FastAPI + Socket.IO API |
| `frontend/` | React + TypeScript + Monaco editor |
| `sandbox/` | Isolated CPython 3.11 code runner |
| `eval/` | Replay harness and evaluation stages |
| `docs/`, `scripts/` | Plan, write-ups and one-off tooling |

## Development

Requires Python 3.11.

```bash
pip install -r requirements-dev.txt
ruff check . && ruff format --check .
pytest
```

## Data

The Edwards 2019 and 2021 CS1 keystroke datasets live under the git-ignored `data/raw/`. See [docs/data.md](docs/data.md) for setup, schema and known issues, then check your copy with:

```bash
python scripts/validate_data.py
```

Rebuild code states from the edit logs (see [docs/replay.md](docs/replay.md)):

```bash
python scripts/replay_cohort.py 2021
```

Open one student's rebuilt files in VS Code:

```bash
python scripts/export_snapshot.py 2021 Student1 Assign10 --open
```

The 2021 students are split 70/10/20 into train, validation and test in the frozen
[data/splits.json](data/splits.json). Check that it still matches the raw data with:

```bash
python scripts/make_splits.py
```

Flag candidate misconception patterns in a code state (see [docs/detectors.md](docs/detectors.md)):

```python
from detectors import analyse

analyse("def add(x, items=[]):\n    items.append(x)\n").findings
```

## Running the stack

```bash
docker compose up --build
```

Starts `api` (:8000), `frontend` (:5173), `postgres:15` (:5432), `redis:7` (:6379), `sandbox` and a CPU `vllm` stand-in (:8200). All app services are stubs that answer `GET /health`. Copy `.env.example` to `.env` to override database credentials.
