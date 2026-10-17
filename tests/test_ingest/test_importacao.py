import json
import os

import pytest

from wolfz.core.ingest import CellType, IngestError, import_file
from wolfz.core.workspace import PROJECT_ID, Workspace, cache_key, default_root, file_sha256


def _arquivos(folder):
    return sorted(p.name for p in folder.iterdir() if not p.name.startswith("."))


def test_importa_xlsx(relatorio_xlsx, workspace):
    result = import_file(relatorio_xlsx, workspace=workspace)
    assert PROJECT_ID.fullmatch(result.project_id)
    assert result.path == workspace.projects_dir / result.project_id
    assert _arquivos(result.path) == ["project.json", "raw.parquet", "structure.json"]
    assert not result.reused

    project = json.loads((result.path / "project.json").read_text(encoding="utf-8"))
    assert project == result.project
    assert project["name"] == "relatorio.xlsx"
    assert project["source"]["format"] == "xlsx"
    assert project["source"]["sheet"] == "Vendas"
    assert project["source"]["sha256"] == file_sha256(relatorio_xlsx)
    assert project["source"]["cache_key"] == cache_key(project["source"]["sha256"], "Vendas", None)
    assert project["raw"] == {"rows": 10, "columns": ["C", "D", "E"]}
    assert [s["name"] for s in project["sheets"]] == ["Vendas", "Oculta", "Interna"]
    assert project["sheets"][1]["hidden"] is True

    structure = json.loads((result.path / "structure.json").read_text(encoding="utf-8"))
    assert structure["merged"] == ["C3:E3"]
    assert structure["formulas"] == {"D8": "=SUM(D6:D7)"}

    raw = result.raw().collect()
    assert raw.row(5) == ("01234567890", "1234.5", "2024-01-31 00:00:00")
    cells = result.cells()
    assert cells.cell(2, 2).bold and cells.cell(2, 2).merged
    assert cells.cell(5, 3).type is CellType.NUMBER


def test_importa_aba_escolhida(exemplo_ods, workspace):
    result = import_file(exemplo_ods, sheet="Outra", workspace=workspace)
    assert result.project["source"]["sheet"] == "Outra"
    assert result.raw().collect().rows() == [("a",)]


def test_importa_xls(exemplo_xls, workspace):
    result = import_file(exemplo_xls, workspace=workspace)
    assert result.project["source"]["format"] == "xls"
    assert result.structure.merged[0].to_a1() == "B2:D2"


def test_importa_csv(tmp_path, workspace):
    path = tmp_path / "dados.csv"
    path.write_bytes("Relatório\nMunicípio;Valor\nSão Paulo;1.234,56\n".encode("cp1252"))
    result = import_file(path, workspace=workspace)
    source = result.project["source"]
    assert (source["format"], source["sheet"], source["encoding"], source["separator"]) == (
        "csv",
        None,
        "cp1252",
        ";",
    )
    assert result.project["sheets"] == []
    assert result.raw().collect().rows() == [
        ("Relatório", None),
        ("Município", "Valor"),
        ("São Paulo", "1.234,56"),
    ]
    assert result.structure.formatting is False
    assert result.structure.sampled_rows == [(0, 2)]
    # O temporário da conversão para UTF-8 não fica no projeto.
    assert _arquivos(result.path) == ["project.json", "raw.parquet", "structure.json"]


def test_reaproveita_raw_pelo_hash(relatorio_xlsx, workspace, tmp_path):
    first = import_file(relatorio_xlsx, workspace=workspace)
    copia = tmp_path / "copia com outro nome.xlsx"
    copia.write_bytes(relatorio_xlsx.read_bytes())
    second = import_file(copia, workspace=workspace)
    assert second.reused
    assert second.project_id != first.project_id
    assert second.project["source"]["cache_key"] == first.project["source"]["cache_key"]
    assert second.project["name"] == "copia com outro nome.xlsx"
    assert second.raw().collect().equals(first.raw().collect())
    assert second.structure == first.structure


def test_outra_aba_nao_reaproveita(relatorio_xlsx, workspace):
    import_file(relatorio_xlsx, workspace=workspace)
    assert not import_file(relatorio_xlsx, sheet="Oculta", workspace=workspace).reused


def test_arquivo_alterado_nao_reaproveita(tmp_path, workspace):
    path = tmp_path / "dados.csv"
    path.write_text("a;b\n1;2\n", encoding="utf-8")
    import_file(path, workspace=workspace)
    path.write_text("a;b\n1;3\n", encoding="utf-8")
    result = import_file(path, workspace=workspace)
    assert not result.reused
    assert result.raw().collect().row(1) == ("1", "3")


def test_reaproveita_csv_guarda_encoding(tmp_path, workspace):
    path = tmp_path / "dados.csv"
    path.write_bytes("a;b\nç;2\n".encode("cp1252"))
    import_file(path, workspace=workspace)
    result = import_file(path, workspace=workspace)
    assert result.reused
    assert result.project["source"]["encoding"] == "cp1252"


def test_cache_sem_raw_e_ignorado(relatorio_xlsx, workspace):
    first = import_file(relatorio_xlsx, workspace=workspace)
    (first.path / "raw.parquet").unlink()
    assert not import_file(relatorio_xlsx, workspace=workspace).reused


def test_falha_nao_deixa_projeto(tmp_path, workspace):
    path = tmp_path / "secreto.xlsx"
    path.write_bytes(b"PK\x03\x04" + b"lixo" * 10)
    with pytest.raises(IngestError):
        import_file(path, workspace=workspace)
    assert not workspace.projects_dir.exists() or list(workspace.projects_dir.iterdir()) == []


def test_falha_na_gravacao_apaga_o_projeto(relatorio_xlsx, workspace, monkeypatch):
    def disco_cheio(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("wolfz.core.ingest._write_parquet", disco_cheio)
    with pytest.raises(OSError):
        import_file(relatorio_xlsx, workspace=workspace)
    assert list(workspace.projects_dir.iterdir()) == []


def test_workspace_padrao_respeita_wolfz_home(tmp_path, monkeypatch):
    monkeypatch.setenv("WOLFZ_HOME", str(tmp_path / "casa"))
    assert default_root() == tmp_path / "casa"
    assert Workspace().root == tmp_path / "casa"
    monkeypatch.delenv("WOLFZ_HOME")
    assert default_root().name == ".wolfz"


@pytest.mark.parametrize("bad", ["../../etc", "01ARZ3NDEKTSV4RRFFQ69G5FA", "01arz3ndektsv4rrffq69g5fav", ""])
def test_id_de_projeto_validado(workspace, bad):
    with pytest.raises(ValueError):
        workspace.project_dir(bad)


def test_projetos_ignora_pastas_estranhas(workspace, relatorio_xlsx):
    result = import_file(relatorio_xlsx, workspace=workspace)
    (workspace.projects_dir / "lixo").mkdir()
    quebrado = workspace.projects_dir / "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    quebrado.mkdir()
    (quebrado / "project.json").write_text("{", encoding="utf-8")
    assert [pid for pid, _ in workspace.projects()] == [result.project_id]


def test_projetos_sem_workspace(tmp_path):
    assert list(Workspace(tmp_path / "nada").projects()) == []


def test_link_ou_copia(tmp_path, monkeypatch):
    from wolfz.core.workspace import link_or_copy

    src = tmp_path / "a"
    src.write_text("x", encoding="utf-8")

    def sem_link(*args):
        raise OSError("sem suporte a hard link")

    monkeypatch.setattr(os, "link", sem_link)
    link_or_copy(src, tmp_path / "b")
    assert (tmp_path / "b").read_text(encoding="utf-8") == "x"
