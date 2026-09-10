import os
import sys

# чтобы импортировался пакет checker из корня проекта
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from checker import config_mod


@pytest.fixture
def cfg():
    return config_mod.load_all()


@pytest.fixture
def brands(cfg):
    return cfg["brands"]


@pytest.fixture
def rules(cfg):
    return cfg["rules"]
