from pathlib import Path

def test_benchmark_corpus_exists():
    assert Path('benchmarks/portfolio-v1.json').exists()
