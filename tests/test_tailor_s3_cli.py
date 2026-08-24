from scripts.tailor_s3 import build_parser, cmd_invoke, cmd_prepare


def test_s3_cli_contract_exists():
    assert callable(cmd_prepare)
    assert callable(cmd_invoke)
    assert build_parser().parse_args(["invoke", "--request", "r", "--banned-words", "b", "--output", "o"]).command == "invoke"
