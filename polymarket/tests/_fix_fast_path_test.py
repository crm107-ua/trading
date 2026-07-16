from pathlib import Path

p = Path(__file__).with_name("test_decision_engine.py")
t = p.read_text(encoding="utf-8")
old = """def test_fast_path_quotes_without_nim():
    snap = _base_snapshot()
    decision, nim = decide_quote_action(snapshot=snap, use_cache=False)
    assert decision.action == "quote"
    assert decision.reason == "rule_fast_path"
    assert decision.source == "rule"
    assert nim is None
"""
new = """def test_fast_path_quotes_without_nim(monkeypatch):
    monkeypatch.setenv("NVIDIA_NIM_MODE", "fast")
    snap = _base_snapshot()
    decision, nim = decide_quote_action(snapshot=snap, use_cache=False)
    assert decision.action == "quote"
    assert decision.reason == "rule_fast_path"
    assert decision.source == "rule"
    assert nim is None
"""
if old not in t:
    raise SystemExit("block not found")
p.write_text(t.replace(old, new, 1), encoding="utf-8")
print("ok")
