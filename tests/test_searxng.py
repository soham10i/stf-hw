from unittest.mock import patch
from services.api.rag import websearch as W


def test_html_to_markdown_preserves_tables_and_headings():
    sample_html = """
    <html><body>
    <nav><a href="/">Home</a></nav>
    <main>
      <h1>Simulation Benchmark</h1>
      <p>Comparing physics engine accuracy and performance:</p>
      <table>
        <tr><th>Engine</th><th>Accuracy</th><th>FPS</th></tr>
        <tr><td>PhysX</td><td>High</td><td>60 Hz</td></tr>
        <tr><td>Bullet</td><td>Medium</td><td>120 Hz</td></tr>
      </table>
    </main>
    <footer>Copyright 2026</footer>
    </body></html>
    """
    res = W.html_to_text(sample_html)
    assert "# Simulation Benchmark" in res
    assert "Comparing physics engine" in res
    assert "| Engine | Accuracy | FPS |" in res
    assert "| PhysX | High | 60 Hz |" in res
    assert "Copyright 2026" not in res  # footer stripped


def test_searxng_search_parsing():
    mock_payload = """
    {
      "results": [
        {
          "url": "https://nvidia.com/physx",
          "title": "NVIDIA PhysX SDK",
          "content": "PhysX simulation engine.",
          "engine": "google"
        },
        {
          "url": "https://pybullet.org",
          "title": "Bullet Physics SDK",
          "content": "Bullet physics engine.",
          "engine": "bing"
        }
      ]
    }
    """
    with patch("services.api.rag.websearch._fetch_searxng", return_value=mock_payload):
        res = W.searxng_search("physics simulation")
        assert len(res) == 2
        assert res[0]["url"] == "https://nvidia.com/physx"
        assert res[0]["title"] == "NVIDIA PhysX SDK"
        assert res[1]["engine"] == "bing"

