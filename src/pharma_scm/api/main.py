"""uvicorn 진입점: uv run uvicorn pharma_scm.api.main:app --host 0.0.0.0 --port 8000"""

from pharma_scm import config
from pharma_scm.api.app import create_app
from pharma_scm.api.settings import Settings

config.load_env()
app = create_app(Settings.from_env())
