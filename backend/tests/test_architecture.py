"""Test the architecture endpoint (Epic 15): it returns the keyed, in-context notes."""

EXPECTED_KEYS = ["queue", "workers", "chaos", "realtime", "guardrails"]


async def test_architecture_returns_keyed_sections(api_client):
    response = await api_client.get("/api/architecture")

    assert response.status_code == 200
    sections = response.json()["sections"]
    # The notes are keyed to the dashboard panes, in order, each with non-empty title and body.
    assert [section["key"] for section in sections] == EXPECTED_KEYS
    for section in sections:
        assert section["title"]
        assert section["body"]
