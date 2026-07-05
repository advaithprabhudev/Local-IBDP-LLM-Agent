from pathlib import Path

from ib_tutor.config import Config, load_config


def test_load_config_defaults_when_missing(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg == Config()


def test_load_config_reads_toml(tmp_path: Path) -> None:
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        '[ollama]\ngeneration_model = "llama3.1"\nembed_model = "mxbai-embed-large"\n'
        "[chunking]\nsize = 256\noverlap = 32\n"
        "[retrieval]\ntop_k = 4\n"
        '[paths]\nsources = "my_sources"\ndata = "my_data"\n'
    )
    cfg = load_config(toml_path)
    assert cfg.generation_model == "llama3.1"
    assert cfg.embed_model == "mxbai-embed-large"
    assert cfg.chunk_size == 256
    assert cfg.chunk_overlap == 32
    assert cfg.top_k == 4
    assert cfg.sources_dir == Path("my_sources")
    assert cfg.data_dir == Path("my_data")
