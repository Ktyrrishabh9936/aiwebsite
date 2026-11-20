import asyncio

import coding_agent


def test_list_files_is_summarized_and_duplicate_is_hidden():
    tree = [
        {"name": "src", "path": "src", "type": "dir", "children": [
            {"name": "App.jsx", "path": "src/App.jsx", "type": "file"},
            {"name": "main.jsx", "path": "src/main.jsx", "type": "file"},
        ]},
        {"name": "package.json", "path": "package.json", "type": "file"},
        {"name": "README.md", "path": "README.md", "type": "file"},
    ]
    calls = 0

    async def list_files():
        nonlocal calls
        calls += 1
        return tree

    state = coding_agent.AgentTurnState()
    result, extra = asyncio.run(coding_agent._execute({"list_files": list_files}, "list_files", {}, state))
    duplicate_result, duplicate_extra = asyncio.run(coding_agent._execute({"list_files": list_files}, "list_files", {}, state))

    assert calls == 1
    assert extra["label"] == "Explored 4 files"
    assert duplicate_extra is None
    assert "Read specific files next" in duplicate_result
    assert "src/App.jsx" in result
    assert "package.json" in result
    assert "do not call list_files again" in result
