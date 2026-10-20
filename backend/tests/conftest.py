import os
import sys
from pathlib import Path

# Тесты работают без сети и без LLM (режим деградации); LLM-путь — через фейковый провайдер.
os.environ["SERUEN_DISABLE_LLM"] = "1"
os.environ["SERUEN_DISABLE_NETWORK"] = "1"
os.environ.setdefault("POIS_PATH", "data/seed/pois_seed.json")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
