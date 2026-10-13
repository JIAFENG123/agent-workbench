from app.agents import agent_keys, get_agent, list_agents


def test_agent_registration():
    keys = agent_keys()
    assert "compliance" in keys
    assert "listing_optimizer" in keys
    assert "doc_qa" in keys

    compliance = get_agent("compliance")
    assert compliance is not None
    assert "kb_search" in compliance.tool_allowlist

    optimizer = get_agent("listing_optimizer")
    assert optimizer is not None
    assert "calculator" in optimizer.tool_allowlist
    assert "kb_search" in optimizer.tool_allowlist

    doc_qa = get_agent("doc_qa")
    assert doc_qa is not None
    assert "kb_search" in doc_qa.tool_allowlist
    assert "calculator" in doc_qa.tool_allowlist

    all_agents = list_agents()
    assert len(all_agents) >= 3
