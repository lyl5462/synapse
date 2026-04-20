"""研发工具 slug 校验（与 API 创建端点一致）。"""

from synapse.api.routes.skills import sanitize_dev_tool_slug


def test_sanitize_dev_tool_slug_accepts_valid() -> None:
    assert sanitize_dev_tool_slug("my-flow") == "my-flow"
    assert sanitize_dev_tool_slug("  My-Flow-2  ") == "my-flow-2"
    assert sanitize_dev_tool_slug("ab") == "ab"


def test_sanitize_dev_tool_slug_rejects_invalid() -> None:
    assert sanitize_dev_tool_slug("a") is None
    assert sanitize_dev_tool_slug("My_Flow") is None
    assert sanitize_dev_tool_slug("flow-") is None
    assert sanitize_dev_tool_slug("-x") is None
    assert sanitize_dev_tool_slug("x" * 49) is None
