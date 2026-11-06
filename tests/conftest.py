import psycopg
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult

from pharma_scm import config


class FakeChat(BaseChatModel):
    """미리 정한 AIMessage를 순서대로 돌려주는 가짜 모델(API 호출 없음)."""

    script: list = []
    i: int = 0

    @property
    def _llm_type(self):
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        m = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        return ChatResult(generations=[ChatGeneration(message=m)])


@pytest.fixture(scope="session")
def db_up():
    try:
        psycopg.connect(config.ADMIN_DSN, connect_timeout=3).close()
    except psycopg.OperationalError:
        return False
    return True


@pytest.fixture
def needs_db(db_up):
    if not db_up:
        pytest.skip("Postgres 없음")
