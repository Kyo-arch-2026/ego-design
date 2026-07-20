"""単体テスト仕様書 5.5 CLI Adapter(UT-CLI-01〜02)。入力正規化部のみ対象。"""

import pytest

from ego.adapters.input.cli import CliInputAdapter, normalize
from ego.core.domain import InputMessage
from ego.core.errors import InputError
from ego.ports.input_port import InputPort


def test_ut_cli_01_argv_normalized_to_domain_type():
    """UT-CLI-01(規約2): argv がドメイン型 InputMessage に変換される。"""
    message = normalize(["record", "転職の", "方針", "--revises", "fact-123"])

    assert isinstance(message, InputMessage)
    assert message.command == "record"
    assert message.text == "転職の 方針"
    assert message.options == {"revises": "fact-123"}
    # argv(list)そのものは Core へ渡らない
    assert not isinstance(message.text, list)

    adapter = CliInputAdapter(["ask", "キーワード"])
    assert isinstance(adapter, InputPort)
    received = adapter.receive()
    assert isinstance(received, InputMessage)
    assert received.command == "ask"
    assert received.text == "キーワード"


@pytest.mark.parametrize("argv", [["fly"], [], ["record", "--revises"]])
def test_ut_cli_02_unknown_command_is_e_input(argv):
    """UT-CLI-02: 未知コマンド等は E_INPUT と一貫形式のメッセージ。"""
    with pytest.raises(InputError) as excinfo:
        normalize(argv)
    assert excinfo.value.code == "E_INPUT"
    assert excinfo.value.display().startswith("[E_INPUT] ")
